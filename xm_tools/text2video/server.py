# -*- coding: utf-8 -*-
"""text2video 网页编辑器：拖拽时间轴调整音频/字幕，改样式与音量，一键渲染出片。

启动（PyCharm 直接运行本文件，或命令行）:
    python server.py            # 打开 http://127.0.0.1:9882
    python server.py -p 9000

接口（浏览器打开 /docs 可交互试用）:
    GET  /                              编辑器页面
    GET  /api/roles                     角色列表（优先问 tts_server，未启动则读 characters/）
    GET  /api/projects                  历史项目列表
    POST /api/projects                  新建项目（后台：切句 -> 逐句合成 -> 排版）
    GET  /api/projects/{id}             项目 JSON + 任务进度
    PUT  /api/projects/{id}             保存编辑（服务端校验不重叠，违规 400）
    POST /api/projects/{id}/relayout    按新的 start/end 重新排版（不改音频内容）
    POST /api/projects/{id}/resynth     {"speed": x} 按新语速重合成全部句子并重排
    POST /api/projects/{id}/render      开始渲染；GET 同路径查进度/结果
    GET  /api/projects/{id}/video       项目源视频（预览用，支持拖动进度）
    GET  /media/{id}/...                项目内文件（wav / 成片 / 字幕）

行为:
    * 合成请求经 tts_server 全局锁串行执行；本项目内任务用后台线程 + 进度字典，前端轮询。
    * 保存时会校验：音频之间间隔 >= min_gap、字幕之间不重叠、时长 > 0，违规返回 400。
"""

import argparse
import json
import os
import sys
import threading
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import render as render_mod
from layout import plan_timing
from pipeline import PROJECTS_DIR, build_project, new_project_dir, save_project, synthesize_segments
from segment import split_text

WEB_DIR = os.path.join(_HERE, "web")
DEFAULT_STYLE = {"font": "Microsoft YaHei", "size": 54, "color": "#FFFFFF",
                 "outline_color": "#000000", "outline_width": 2, "shadow": 0,
                 "x": None, "y": None}

app = FastAPI(title="text2video 编辑器")
_jobs = {}
_jobs_lock = threading.Lock()


def _job_set(pid, **kw):
    with _jobs_lock:
        _jobs.setdefault(pid, {}).update(kw)


def _job_get(pid):
    with _jobs_lock:
        return dict(_jobs.get(pid) or {})


def _dir_of(pid):
    return os.path.join(PROJECTS_DIR, pid)


def _project_dir(pid):
    d = _dir_of(pid)
    if not os.path.isfile(os.path.join(d, "project.json")):
        raise HTTPException(404, "项目不存在: %s" % pid)
    return d


def _load(pid):
    with open(os.path.join(_project_dir(pid), "project.json"), encoding="utf-8") as f:
        return json.load(f)


def _save(pid, project):
    d = _dir_of(pid)
    os.makedirs(d, exist_ok=True)
    save_project(project, os.path.join(d, "project.json"))


def _apply_layout(project, plan):
    """把 plan 的开始时间写回 segments；与音频同步的字幕跟着走，否则平移相同增量。"""
    for s, start in zip(project["segments"], plan["starts"]):
        old = s["start"]
        start = round(float(start), 3)
        delta = start - old
        sub = s["subtitle"]
        linked = abs(sub["start"] - old) < 1e-6
        s["start"] = start
        if linked:
            sub["start"] = start
        else:
            sub["start"] = round(max(0.0, sub["start"] + delta), 3)
    tl = project["timeline"]
    tl.update({
        "start_time": plan["start_time"],
        "end_time": round(plan["end_time"], 3),
        "end_time_auto": plan["available"] is None,
        "default_gap": plan["default_gap"],
        "min_gap": plan["min_gap"],
        "gap": round(plan["gap"], 3),
        "fit": plan["fit"],
        "overflow_seconds": round(plan["overflow_seconds"], 3),
    })


def _validate(project):
    """返回错误列表（空 = 通过）。音频要求间隔 >= min_gap，字幕只要求不重叠。"""
    errs = []
    tl = project.get("timeline") or {}
    min_gap = float(tl.get("min_gap", 0.08))
    start0 = float(tl.get("start_time", 0.0))
    segs = project.get("segments") or []
    if not segs:
        return ["项目没有句子"]
    for s in segs:
        if s.get("duration", 0) <= 0 or (s.get("subtitle") or {}).get("duration", 0) <= 0:
            errs.append("第%s句时长必须大于 0" % s.get("id"))
    audio = sorted(segs, key=lambda s: s["start"])
    if audio[0]["start"] < start0 - 1e-6:
        errs.append("第%s句在时间轴起点之前" % audio[0].get("id"))
    for a, b in zip(audio, audio[1:]):
        gap = b["start"] - (a["start"] + a["duration"])
        if gap < min_gap - 1e-6:
            errs.append("第%s/%s句间隔 %.3fs < 最小 %.3fs" % (a.get("id"), b.get("id"), gap, min_gap))
    subs = sorted(segs, key=lambda s: s["subtitle"]["start"])
    for a, b in zip(subs, subs[1:]):
        sa, sb = a["subtitle"], b["subtitle"]
        if sb["start"] < sa["start"] + sa["duration"] - 1e-6:
            errs.append("第%s/%s句字幕重叠" % (a.get("id"), b.get("id")))
    return errs


# ---------------------------------------------------------------- API

@app.get("/api/roles")
def api_roles():
    try:
        import requests
        r = requests.get("http://127.0.0.1:9881/roles", timeout=3)
        if r.ok:
            return [x["name"] for x in r.json()]
    except Exception:
        pass
    import glob
    import yaml
    root = os.path.dirname(os.path.dirname(_HERE))
    out = []
    for f in glob.glob(os.path.join(root, "characters", "*.y*ml")):
        try:
            cfg = yaml.safe_load(open(f, encoding="utf-8")) or {}
        except Exception:
            continue
        out.append(str(cfg.get("name") or os.path.splitext(os.path.basename(f))[0]))
    return sorted(out)


@app.get("/api/projects")
def api_projects():
    items = []
    if os.path.isdir(PROJECTS_DIR):
        for name in os.listdir(PROJECTS_DIR):
            pj = os.path.join(PROJECTS_DIR, name, "project.json")
            if not os.path.isfile(pj):
                continue
            try:
                with open(pj, encoding="utf-8") as f:
                    p = json.load(f)
            except Exception:
                continue
            segs = p.get("segments") or []
            items.append({
                "id": name, "mode": p.get("mode"), "role": p.get("role"),
                "text": segs[0]["subtitle_text"][:24] if segs else "",
                "n": len(segs), "mtime": os.path.getmtime(pj),
                "output": (p.get("render") or {}).get("output"),
                "stage": _job_get(name).get("stage"),
            })
    items.sort(key=lambda x: -x["mtime"])
    return items


@app.post("/api/projects")
def api_create(body: dict = Body(...)):
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "text 不能为空")
    video = (body.get("video") or "").strip()
    source = None
    if video:
        if not os.path.isfile(video):
            raise HTTPException(400, "视频文件不存在：%s" % video)
        info = render_mod.probe_video(video)
        source = {"video": video, "duration": round(info["duration"], 3),
                  "width": info["width"], "height": info["height"],
                  "fps": info["fps"], "has_audio": info["has_audio"]}
    mode = "video" if video else "audio_only"

    def _f(key, default):
        v = body.get(key)
        return default if v in (None, "") else float(v)

    end = body.get("end_time")
    end = None if end in (None, "", "null") else float(end)
    opts = {
        "role": body.get("role") or "洛天依",
        "lang": body.get("lang") or "zh",
        "speed": _f("speed", 1.0),
        "start_time": _f("start_time", 0.0),
        "end_time": end,
        "gap": _f("gap", 0.3),
        "min_gap": _f("min_gap", 0.08),
        "min_chars": int(_f("min_chars", 5)),
        "max_chars": int(_f("max_chars", 24)),
        "merge_max": int(_f("merge_max", 14)),
        "original_volume_db": _f("original_volume_db", 0.0),
        "tts_volume_db": _f("tts_volume_db", 0.0),
        "style": body.get("style") or dict(DEFAULT_STYLE),
    }

    project_dir = new_project_dir()
    pid = os.path.basename(project_dir)

    def worker():
        try:
            _job_set(pid, stage="segment", done=0, total=0, message="切句中…", error=None, output=None)
            segments = split_text(text, opts["min_chars"], opts["max_chars"], opts["merge_max"])
            if not segments:
                raise ValueError("切句结果为空")
            n = len(segments)
            _job_set(pid, stage="synth", done=0, total=n, message="合成 0/%d" % n)

            def on_seg(i, total, dur, seg):
                _job_set(pid, done=i, total=total,
                         message="合成 %d/%d：%s" % (i, total, seg["subtitle_text"]))

            wavs, durations = synthesize_segments(
                segments, opts["role"], opts["lang"], opts["speed"],
                os.path.join(project_dir, "wavs"), on_segment=on_seg)
            _job_set(pid, stage="layout", message="排版中…")
            plan = plan_timing(durations, opts["start_time"], opts["end_time"],
                               opts["gap"], opts["min_gap"])
            project = build_project(
                segments, durations, plan, mode, opts["role"], opts["lang"], opts["speed"],
                opts["style"],
                mix={"original_volume_db": opts["original_volume_db"],
                     "tts_volume_db": opts["tts_volume_db"]},
                segment_opts={"min_chars": opts["min_chars"], "max_chars": opts["max_chars"],
                              "merge_max": opts["merge_max"]},
                source=source, project_id=pid)
            _save(pid, project)
            _job_set(pid, stage="done", message="完成")
        except Exception as e:
            traceback.print_exc()
            _job_set(pid, stage="error", error=str(e), message="失败：%s" % e)

    threading.Thread(target=worker, daemon=True).start()
    return {"id": pid, "job": _job_get(pid)}


@app.get("/api/projects/{pid}")
def api_get(pid):
    pj = os.path.join(_dir_of(pid), "project.json")
    job = _job_get(pid)
    if os.path.isfile(pj):
        with open(pj, encoding="utf-8") as f:
            return {"project": json.load(f), "job": job}
    if os.path.isdir(_dir_of(pid)) or job:
        return {"project": None, "job": job}   # 合成中的新项目：还没有 project.json
    raise HTTPException(404, "项目不存在: %s" % pid)


@app.put("/api/projects/{pid}")
def api_put(pid, project: dict = Body(...)):
    _load(pid)  # 不存在则 404
    errs = _validate(project)
    if errs:
        raise HTTPException(400, "；".join(errs[:5]))
    _save(pid, project)
    return {"ok": True}


@app.post("/api/projects/{pid}/relayout")
def api_relayout(pid, body: dict = Body(default={})):
    project = _load(pid)
    tl = project["timeline"]
    st = float(body.get("start_time", tl["start_time"]))
    end = body.get("end_time", tl["end_time"])
    end = None if end in (None, "", "null") else float(end)
    gap = float(body.get("default_gap", tl["default_gap"]))
    mg = float(body.get("min_gap", tl["min_gap"]))
    try:
        plan = plan_timing([s["duration"] for s in project["segments"]], st, end, gap, mg)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _apply_layout(project, plan)
    _save(pid, project)
    return {"project": project}


@app.post("/api/projects/{pid}/resynth")
def api_resynth(pid, body: dict = Body(...)):
    speed = float(body.get("speed") or 0)
    if not 0.5 <= speed <= 2.0:
        raise HTTPException(400, "speed 需在 0.5 ~ 2.0 之间")
    project = _load(pid)
    project_dir = _project_dir(pid)

    def worker():
        try:
            segs = [{"text": s["text"], "subtitle_text": s["subtitle_text"]}
                    for s in project["segments"]]
            n = len(segs)
            _job_set(pid, stage="synth", done=0, total=n,
                     message="按语速 %.2f 重合成…" % speed, error=None, output=None)

            def on_seg(i, total, dur, seg):
                _job_set(pid, done=i, total=total, message="合成 %d/%d" % (i, total))

            wavs, durs = synthesize_segments(segs, project["role"], project["lang"], speed,
                                             os.path.join(project_dir, "wavs"), on_segment=on_seg)
            for s, d in zip(project["segments"], durs):
                sub = s["subtitle"]
                if abs(sub["duration"] - s["duration"]) < 1e-6 and abs(sub["start"] - s["start"]) < 1e-6:
                    sub["duration"] = round(float(d), 3)   # 与音频联动的字幕同步新时长
                s["duration"] = round(float(d), 3)
            tl = project["timeline"]
            end = None if tl.get("end_time_auto") else tl["end_time"]
            plan = plan_timing([s["duration"] for s in project["segments"]],
                               tl["start_time"], end, tl["default_gap"], tl["min_gap"])
            _apply_layout(project, plan)
            project["speed"] = speed
            _save(pid, project)
            _job_set(pid, stage="done", message="完成")
        except Exception as e:
            traceback.print_exc()
            _job_set(pid, stage="error", error=str(e), message="失败：%s" % e)

    threading.Thread(target=worker, daemon=True).start()
    return {"job": _job_get(pid)}


@app.post("/api/projects/{pid}/render")
def api_render(pid):
    _load(pid)
    if _job_get(pid).get("stage") == "rendering":
        raise HTTPException(409, "渲染任务进行中")
    _job_set(pid, stage="rendering", message="渲染中…", error=None, output=None)

    def worker():
        try:
            project = _load(pid)
            out = render_mod.render_project(project, _project_dir(pid), None)
            _save(pid, project)
            _job_set(pid, stage="done", output=out, message="渲染完成")
        except Exception as e:
            traceback.print_exc()
            _job_set(pid, stage="error", error=str(e), message="渲染失败：%s" % e)

    threading.Thread(target=worker, daemon=True).start()
    return {"job": _job_get(pid)}


@app.get("/api/projects/{pid}/render")
def api_render_state(pid):
    _load(pid)
    job = _job_get(pid)
    out = job.get("output")
    if out and os.path.isfile(out):
        rel = os.path.relpath(out, PROJECTS_DIR).replace("\\", "/")
        job["output_url"] = "/media/" + rel
        job["output_name"] = os.path.basename(out)
    return {"job": job}


@app.get("/api/projects/{pid}/video")
def api_video(pid):
    project = _load(pid)
    v = (project.get("source") or {}).get("video")
    if not v or not os.path.isfile(v):
        raise HTTPException(404, "项目没有可用的视频文件")
    return FileResponse(v)


os.makedirs(PROJECTS_DIR, exist_ok=True)
app.mount("/media", StaticFiles(directory=PROJECTS_DIR), name="media")
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="text2video 网页编辑器")
    parser.add_argument("-a", "--host", default="127.0.0.1", help="绑定地址（默认仅本机）")
    parser.add_argument("-p", "--port", type=int, default=9882, help="端口（默认 9882）")
    args = parser.parse_args()
    print("编辑器已启动：http://%s:%d   （Ctrl+C 退出）" % (args.host, args.port))
    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
