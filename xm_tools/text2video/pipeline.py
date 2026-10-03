# -*- coding: utf-8 -*-
"""编排：切句 -> 逐句合成（实测时长）-> 排版 -> 项目 JSON。

被 text2video_run.py（PyCharm 入口）调用；后续 CLI / 网页编辑器共用同一套函数。
每次任务一个目录：projects/<id>/（project.json + wavs/segNNN.wav + 字幕 + 成片）。
"""

import json
import os
import sys
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

PROJECTS_DIR = os.path.join(_HERE, "projects")


def new_project_id():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def new_project_dir(project_id=None):
    """建一个项目目录（projects/<id>/wavs/），返回目录路径（重名自动加后缀）。"""
    pid = project_id or new_project_id()
    d = os.path.join(PROJECTS_DIR, pid)
    k = 1
    while os.path.exists(d):
        k += 1
        d = os.path.join(PROJECTS_DIR, "%s_%02d" % (pid, k))
    os.makedirs(os.path.join(d, "wavs"))
    return d


def synthesize_segments(segments, role, lang, speed=1.0, wav_dir=None, progress=None,
                        on_segment=None, timeout=300):
    """逐句合成语音，返回 (wav_paths, durations)。

    wav 保存为 wav_dir/segNNN.wav；走常驻 TTS 服务（tts_client，未启动会自动拉起）。
    on_segment(i, n, duration, segment) 在每句完成后回调（网页编辑器用它报进度）。
    """
    from tts_client import synthesize

    os.makedirs(wav_dir, exist_ok=True)
    import soundfile as sf

    wavs, durs = [], []
    n = len(segments)
    for i, seg in enumerate(segments, 1):
        dst = os.path.join(wav_dir, "seg%03d.wav" % i)
        if progress:
            progress("  [%d/%d] 合成中…" % (i, n))
        try:
            synthesize(role=role, text=seg["text"], lang=lang, speed=speed,
                       save_to=dst, timeout=timeout)
        except Exception as e:
            raise RuntimeError("第 %d 句合成失败（%s）：%s" % (i, seg["subtitle_text"], e))
        dur = float(sf.info(dst).duration)
        wavs.append(dst)
        durs.append(dur)
        if on_segment:
            on_segment(i, n, dur, seg)
        if progress:
            progress("  [%d/%d] 完成 %.2fs：%s" % (i, n, dur, seg["subtitle_text"]))
    return wavs, durs


def build_project(segments, durations, plan, mode, role, lang, speed,
                  style, mix, segment_opts, source=None, project_id=None,
                  render_quality="lossless"):
    """组装项目 dict（结构见 docs/cn/plan-text2video.md 3.10）。"""
    if project_id is None:
        project_id = new_project_id()
    seg_objs = []
    for i, (seg, d) in enumerate(zip(segments, durations), 1):
        st = round(float(plan["starts"][i - 1]), 3)
        d = round(float(d), 3)
        seg_objs.append({
            "id": i,
            "text": seg["text"],
            "subtitle_text": seg["subtitle_text"],
            "wav": "wavs/seg%03d.wav" % i,
            "role": role,
            "start": st,
            "duration": d,
            "volume_db": 0.0,
            "subtitle": {"start": st, "duration": d, "offset": 0.0,
                         "x": None, "y": None, "style": {}},
        })
    return {
        "id": project_id,
        "mode": mode,
        "source": source,
        "role": role,
        "lang": lang,
        "speed": speed,
        "segment_opts": segment_opts,
        "timeline": {
            "start_time": plan["start_time"],
            "end_time": round(plan["end_time"], 3),
            "end_time_auto": plan["available"] is None,
            "default_gap": plan["default_gap"],
            "min_gap": plan["min_gap"],
            "gap": round(plan["gap"], 3),
            "fit": plan["fit"],
            "overflow_seconds": round(plan["overflow_seconds"], 3),
        },
        "mix": mix,
        "style_default": style,
        "segments": seg_objs,
        "render": {"status": "none", "output": None, "ffmpeg": None, "quality": render_quality},
    }


def save_project(project, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(project, f, ensure_ascii=False, indent=2)
    return path
