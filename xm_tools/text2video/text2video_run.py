# -*- coding: utf-8 -*-
"""纯文本 -> 配音 + 字幕 + 视频：PyCharm 点击运行入口（完整流程）。

用法：修改下面「参数区」，然后右键 Run 'text2video_run'。
流程：切句 -> 逐句合成（复用常驻 TTS 服务，首句可能需 30~60 秒加载模型）
      -> 排版（不重叠；自动适配 END_TIME）-> ffmpeg 混音 + 烧字幕出片。

产出在 projects/<任务id>/ 里：project.json（可编辑）、wavs/、subtitles.ass/.srt、成片。

Python 调用：from text2video_run import run
    run(text="...", video=r"D:\\in.mp4", role="洛天依", lang="zh")
"""

import os
import sys
import time

# ==================== 参数区（在这里改） ====================

# 要配音的文本；也可以填一个 .txt 文件路径（自动读取文件内容）
TEXT = """大家好。欢迎来到我的博客。今天我们聊一聊，怎么用一段文本自动生成配音和字幕。"""

VIDEO = ""            # 输入视频路径；留空 = 无视频模式（只出音频 + 字幕文件）
OUT = ""              # 成片输出路径；留空 = 自动放到 projects/<任务id>/ 里

ROLE = "洛天依"        # 角色名（python tts_infer.py --list 可查全部）
LANG = "zh"           # zh / ja / en / ko / yue
SPEED = 1.0           # 语速，1.0 为正常

START_TIME = 0.0      # 时间轴起点（秒）
END_TIME = None       # 时间轴终点（秒）；None = 自动估计

# —— 切句（一般不用改）——
MIN_CHARS = 5         # 短于此长度的句子会与相邻句合并
MAX_CHARS = 24        # 长于此长度的句子会在逗号处再切
MERGE_MAX = 14        # 合并后的字幕长度上限

# —— 停顿与音量（一般不用改）——
GAP = 0.3             # 默认句间停顿（秒）
MIN_GAP = 0.08        # 压缩时允许的最小句间停顿（秒）
ORIGINAL_VOLUME_DB = 0.0   # 原声音量（dB，0 = 不变）
TTS_VOLUME_DB = 0.0        # 配音音量（dB，0 = 不变）

# —— 字幕默认样式（后续也能在网页前端里调）——
STYLE = {
    "font": "Microsoft YaHei",   # 字体
    "size": 54,                  # 字号（按 1080p 视频；其他分辨率自动缩放）
    "color": "#FFFFFF",          # 文字颜色
    "outline_color": "#000000",  # 描边颜色
    "outline_width": 2,          # 描边宽度
    "shadow": 0,                 # 阴影（0 = 无）
    "x": None,                   # 水平位置（像素）；None = 水平居中
    "y": None,                   # 垂直位置（像素）；None = 底部（留 8% 边距）
}

# —— 导出质量：standard（快、小）/ high（字幕清晰）/ lossless（默认，视频无损、文件最大）——
QUALITY = "lossless"

# ==========================================================

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from layout import check_no_overlap, fit_summary, format_table, plan_timing  # noqa: E402
from pipeline import build_project, new_project_dir, save_project, synthesize_segments  # noqa: E402
from render import probe_video, render_project  # noqa: E402
from segment import split_text  # noqa: E402


def _load_text(text):
    t = text.strip()
    if not t:
        return text
    try:
        if "\n" not in t and os.path.isfile(t):
            with open(t, encoding="utf-8") as f:
                return f.read()
    except OSError:
        pass
    return text


def run(text, video="", out="", role=ROLE, lang=LANG, speed=SPEED,
        start_time=START_TIME, end_time=END_TIME,
        min_chars=MIN_CHARS, max_chars=MAX_CHARS, merge_max=MERGE_MAX,
        gap=GAP, min_gap=MIN_GAP,
        original_volume_db=ORIGINAL_VOLUME_DB, tts_volume_db=TTS_VOLUME_DB,
        style=None, quality=QUALITY, progress=print):
    """完整流程：切句 -> 逐句合成 -> 排版 -> 出片。返回结果 dict。"""
    style = dict(STYLE) if style is None else dict(style)
    text = _load_text(text)
    if not text.strip():
        raise ValueError("TEXT 为空，请填写要配音的文本")
    video = (video or "").strip()
    if video and not os.path.isfile(video):
        raise FileNotFoundError("视频不存在：%s" % video)

    source = None
    if video:
        info = probe_video(video)
        source = {"video": video, "duration": round(info["duration"], 3),
                  "width": info["width"], "height": info["height"],
                  "fps": info["fps"], "has_audio": info["has_audio"]}
    mode = "video" if video else "audio_only"

    progress("=" * 64)
    progress("纯文本 -> 配音 + 字幕 + 视频（角色: %s | 语言: %s | 语速: %.2f）" % (role, lang, speed))
    if video:
        progress("视频: %s（%.2fs %dx%d %s原声）" % (
            video, info["duration"], info["width"], info["height"],
            "" if info["has_audio"] else "无"))
    else:
        progress("模式: 无视频（输出 整轨 wav + ass + srt）")
    progress("=" * 64)

    segments = split_text(text, min_chars, max_chars, merge_max)
    if not segments:
        raise ValueError("切句结果为空")
    progress("切句：共 %d 句" % len(segments))

    project_dir = new_project_dir()
    wav_dir = os.path.join(project_dir, "wavs")
    progress("逐句合成（首次约 30~60 秒加载模型）…")
    t0 = time.time()
    wavs, durations = synthesize_segments(segments, role, lang, speed, wav_dir, progress)
    progress("合成完成：%d 句，用时 %.1fs" % (len(wavs), time.time() - t0))

    plan = plan_timing(durations, start_time, end_time, gap, min_gap)
    progress("")
    progress("切句与排版结果（时长为实测）：")
    progress(format_table(segments, plan))
    progress("排版结论：%s" % fit_summary(plan))
    bad = check_no_overlap(plan["starts"], plan["durations"], min_gap)
    if bad:
        raise RuntimeError("不重叠校验失败（这是 bug，请反馈）：%s" % bad)
    if plan["fit"] == "overflow":
        suggest = speed * plan["needed_min"] / plan["available"]
        progress("提示：音频超出 END_TIME，可选 调大 END_TIME / 调小文本 / 把 SPEED 调到约 %.2f%s"
                 % (min(suggest, 1.25), "" if suggest <= 1.25 else "（已超 1.25 上限，建议删减文本）"))

    project = build_project(
        segments, durations, plan, mode, role, lang, speed, style,
        mix={"original_volume_db": original_volume_db, "tts_volume_db": tts_volume_db},
        segment_opts={"min_chars": min_chars, "max_chars": max_chars, "merge_max": merge_max},
        source=source, project_id=os.path.basename(project_dir), render_quality=quality)
    save_project(project, os.path.join(project_dir, "project.json"))

    out = (out or "").strip()
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    progress("渲染…")
    out_path = render_project(project, project_dir, out or None, progress=progress)
    save_project(project, os.path.join(project_dir, "project.json"))

    progress("")
    progress("完成！成片：%s" % out_path)
    if mode == "audio_only":
        progress("字幕：%s" % os.path.join(project_dir, "subtitles.ass"))
        progress("      %s" % os.path.join(project_dir, "subtitles.srt"))
    progress("项目文件：%s（之后可在网页编辑器里继续调整）" % os.path.join(project_dir, "project.json"))
    return {"project": project, "project_dir": project_dir, "output": out_path,
            "segments": segments, "plan": plan, "wavs": wavs}


def main():
    run(TEXT, VIDEO, OUT)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    main()
