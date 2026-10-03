# -*- coding: utf-8 -*-
"""ffmpeg 渲染：把项目（逐句 wav + 时间轴 + 字幕）合成成片。

    * 视频模式：原声（可调音量）+ 逐句配音（adelay 到各自起点）混音 -> AAC；
      ASS 字幕（\\pos 定位 + 样式）烧录进画面；视频短于时间轴时冻结末帧补齐；
    * 无视频模式：输出整轨 mix.wav + subtitles.ass + subtitles.srt。

ffmpeg 选择：自动探测带 libass 的（本机 = PATH 里 Gyan 版）；
conda 环境内的 ffmpeg 不带 libass（已实测），会被跳过。
渲染时工作目录切到项目目录并只传相对文件名，避免 Windows 路径转义坑。
"""

import json
import os
import re
import shutil
import subprocess

_FALLBACK_FFMPEG = r"C:\Users\Administrator\.conda\envs\GPTSoVits\Library\bin\ffmpeg.exe"
_ffmpeg_cache = None

# 导出质量档位：视频是"烧字幕"重编码，字幕清晰度对 CRF 很敏感（CRF 越低越清晰、文件越大）
# lossless 用 crf=0（逐像素无损）；该档 preset 只影响文件大小/编码速度，不影响画质
QUALITY_PRESETS = {
    "standard": {"crf": "18", "preset": "medium", "abitrate": "192k"},
    "high": {"crf": "12", "preset": "slow", "abitrate": "256k"},
    "lossless": {"crf": "0", "preset": "medium", "abitrate": "320k"},
}
DEFAULT_QUALITY = "lossless"


# ---------------------------------------------------------------- ffmpeg / ffprobe

def _has_libass(ffmpeg):
    try:
        out = subprocess.run([ffmpeg, "-hide_banner", "-filters"],
                             capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=60)
        return bool(re.search(r"^\s*\S+\s+(ass|subtitles)\s+", out.stdout, re.M))
    except (OSError, subprocess.SubprocessError):
        return False


def pick_ffmpeg():
    """挑一个带 libass 字幕滤镜的 ffmpeg（优先 PATH，其次 conda 环境）。"""
    global _ffmpeg_cache
    if _ffmpeg_cache:
        return _ffmpeg_cache
    candidates = []
    p = shutil.which("ffmpeg")
    if p:
        candidates.append(p)
    if os.path.exists(_FALLBACK_FFMPEG) and _FALLBACK_FFMPEG not in candidates:
        candidates.append(_FALLBACK_FFMPEG)
    for c in candidates:
        if _has_libass(c):
            _ffmpeg_cache = c
            return c
    raise RuntimeError("找不到带 libass（字幕滤镜）的 ffmpeg，已尝试：%s" % candidates)


def pick_ffprobe():
    p = shutil.which("ffprobe")
    if p:
        return p
    p = os.path.join(os.path.dirname(pick_ffmpeg()), "ffprobe.exe")
    if os.path.exists(p):
        return p
    raise RuntimeError("找不到 ffprobe（PATH 或 ffmpeg 同目录）")


def _parse_fps(s):
    if not s or s == "0/0":
        return None
    if "/" in s:
        a, b = s.split("/", 1)
        b = float(b)
        return round(float(a) / b, 3) if b else None
    return float(s)


def probe_video(path):
    """读取视频信息：{duration, width, height, fps, has_audio}。"""
    out = subprocess.run(
        [pick_ffprobe(), "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", path],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if out.returncode != 0:
        raise RuntimeError("ffprobe 读取失败：%s" % out.stderr.strip()[-300:])
    data = json.loads(out.stdout)
    info = {"duration": float(data["format"]["duration"]), "width": 0, "height": 0,
            "fps": None, "has_audio": False}
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and not info["width"]:
            info["width"] = int(s.get("width") or 0)
            info["height"] = int(s.get("height") or 0)
            info["fps"] = _parse_fps(s.get("avg_frame_rate") or s.get("r_frame_rate"))
        elif s.get("codec_type") == "audio":
            info["has_audio"] = True
    return info


# ---------------------------------------------------------------- 字幕（ASS / SRT）

def _ass_color(hex_color):
    h = (hex_color or "#FFFFFF").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = h[0:2], h[2:4], h[4:6]
    return "&H00%s%s%s" % (b.upper(), g.upper(), r.upper())


def _ass_escape(text):
    return (text.replace("\\", "＼").replace("{", "｛").replace("}", "｝")
            .replace("\r", " ").replace("\n", " "))


def _ass_time(t):
    t = max(0.0, float(t))
    h = int(t // 3600)
    m = int(t % 3600 // 60)
    return "%d:%02d:%05.2f" % (h, m, t % 60)


def _srt_time(t):
    ms = int(round(max(0.0, float(t)) * 1000))
    return "%02d:%02d:%02d,%03d" % (ms // 3600000, ms % 3600000 // 60000,
                                    ms % 60000 // 1000, ms % 1000)


def build_ass(segments, style, width, height):
    """按视频分辨率生成 ASS：字号/描边按 1080p 标准等比缩放；x/y 为 None 时底部居中。

    每句可用 subtitle.style 覆盖 字号/颜色/描边色/描边宽/阴影（内联标签），
    subtitle.x/y 覆盖位置（优先级：单句 > style 全局 > 默认）。
    """
    scale = height / 1080.0
    font_size = max(8, round(style.get("size", 54) * scale))
    outline = max(0, round(style.get("outline_width", 2) * scale))
    shadow = max(0, round(style.get("shadow", 0) * scale))
    default_x = width // 2
    default_y = height - round(height * 0.08)
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: %d\n"
        "PlayResY: %d\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,%s,%d,%s,%s,%s,&H80000000,0,0,0,0,100,100,0,0,1,%d,%d,2,0,0,0,1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        % (width, height,
           style.get("font", "Microsoft YaHei"), font_size,
           _ass_color(style.get("color", "#FFFFFF")),
           _ass_color(style.get("color", "#FFFFFF")),
           _ass_color(style.get("outline_color", "#000000")),
           outline, shadow))
    lines = []
    for seg in segments:
        sub = seg["subtitle"]
        ov = sub.get("style") or {}
        x = sub.get("x")
        if x is None:
            x = style.get("x")
        x = default_x if x is None else int(x)
        y = sub.get("y")
        if y is None:
            y = style.get("y")
        y = default_y if y is None else int(y)
        size = max(8, round(ov.get("size", style.get("size", 54)) * scale))
        color = ov.get("color") or style.get("color", "#FFFFFF")
        oc = ov.get("outline_color") or style.get("outline_color", "#000000")
        ow = max(0, round(ov.get("outline_width", style.get("outline_width", 2)) * scale))
        sh = max(0, round(ov.get("shadow", style.get("shadow", 0)) * scale))
        st = sub["start"] + sub.get("offset", 0.0)
        tags = ("\\pos(%d,%d)\\fs%d\\c%s\\3c%s\\bord%d\\shad%d"
                % (int(x), int(y), size, _ass_color(color), _ass_color(oc), ow, sh))
        lines.append("Dialogue: 0,%s,%s,Default,,0,0,0,,{%s}%s" % (
            _ass_time(st), _ass_time(st + sub["duration"]), tags,
            _ass_escape(seg["subtitle_text"])))
    return header + "\n".join(lines) + "\n"


def build_srt(segments):
    out = []
    for i, seg in enumerate(segments, 1):
        sub = seg["subtitle"]
        st = sub["start"] + sub.get("offset", 0.0)
        out.append("%d\n%s --> %s\n%s\n" % (i, _srt_time(st), _srt_time(st + sub["duration"]),
                                            seg["subtitle_text"]))
    return "\n".join(out)


# ---------------------------------------------------------------- 音频混音图

def _audio_graph(project, wav_base, has_original):
    """逐句 adelay 到各自起点 + 音量 -> 与原声 amix（normalize=0）-> 安全限幅。

    wav_base：第一句 wav 在 ffmpeg 输入里的序号（视频模式 = 1，因为输入 0 是视频；无视频模式 = 0）。
    has_original：视频自带音轨时把输入 0 的原声也混进来。
    """
    mix = project["mix"]
    segments = project["segments"]
    parts, labels = [], []
    base = wav_base
    if has_original:
        parts.append("[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                     "volume=%.1fdB[orig]" % mix.get("original_volume_db", 0.0))
        labels.append("[orig]")
    for i, s in enumerate(segments):
        ms = int(round(float(s["start"]) * 1000))
        vol = float(s.get("volume_db", 0.0)) + float(mix.get("tts_volume_db", 0.0))
        parts.append("[%d:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                     "volume=%.1fdB,adelay=%d:all=1[seg%d]" % (base + i, vol, ms, i))
        labels.append("[seg%d]" % i)
    parts.append("%samix=inputs=%d:normalize=0:duration=longest,"
                 "alimiter=limit=0.95:level=0[aout]" % ("".join(labels), len(labels)))
    return ";".join(parts)


# ---------------------------------------------------------------- 渲染

def render_project(project, project_dir, out_path=None, progress=None):
    """渲染项目：写 subtitles.ass/.srt，再调 ffmpeg 出片。返回输出路径。"""
    mode = project["mode"]
    segments = project["segments"]
    if not segments:
        raise ValueError("项目里没有句子，无法渲染")
    src = project.get("source") or {}

    # 字幕文件（渲染时 cwd = 项目目录，只用相对文件名，避开 Windows 路径转义坑）
    if mode == "video":
        width = int(src.get("width") or 1920)
        height = int(src.get("height") or 1080)
    else:
        width, height = 1920, 1080  # 无视频模式：ASS 仅作附带产物，用 1080p 画布
    with open(os.path.join(project_dir, "subtitles.ass"), "w", encoding="utf-8") as f:
        f.write(build_ass(segments, project["style_default"], width, height))
    with open(os.path.join(project_dir, "subtitles.srt"), "w", encoding="utf-8") as f:
        f.write(build_srt(segments))

    if progress:
        progress("  写字幕文件：subtitles.ass / subtitles.srt")

    wav_inputs = []
    for s in segments:
        wav_inputs += ["-i", os.path.join(project_dir, s["wav"])]

    quality = (project.get("render") or {}).get("quality") or DEFAULT_QUALITY
    if quality not in QUALITY_PRESETS:
        quality = DEFAULT_QUALITY
    qopt = QUALITY_PRESETS[quality]

    if mode == "video":
        if out_path is None:
            out_path = os.path.join(project_dir, "out.mp4")
        timeline_end = float(project["timeline"]["end_time"])
        extend = max(0.0, timeline_end + 0.2 - float(src.get("duration") or 0.0))
        vfilter = "[0:v]"
        if extend > 0.01:
            vfilter += "tpad=stop_mode=clone:stop_duration=%.2f," % extend
            if progress:
                progress("  视频比时间轴短 %.2fs，将冻结最后一帧补齐" % extend)
        vfilter += "ass=subtitles.ass[vout]"
        graph = vfilter + ";" + _audio_graph(project, 1, bool(src.get("has_audio")))
        if progress:
            progress("  导出质量：%s（视频 crf=%s preset=%s，音频 %s）"
                     % (quality, qopt["crf"], qopt["preset"], qopt["abitrate"]))
        cmd = ([pick_ffmpeg(), "-y", "-i", src["video"]] + wav_inputs +
               ["-filter_complex", graph,
                "-map", "[vout]", "-map", "[aout]",
                "-c:v", "libx264", "-crf", qopt["crf"], "-preset", qopt["preset"],
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", qopt["abitrate"], "-movflags", "+faststart",
                out_path])
    else:
        if out_path is None:
            out_path = os.path.join(project_dir, "mix.wav")
        graph = _audio_graph(project, 0, False)
        cmd = ([pick_ffmpeg(), "-y"] + wav_inputs +
               ["-filter_complex", graph, "-map", "[aout]",
                "-c:a", "pcm_s16le", out_path])

    if progress:
        progress("  ffmpeg 渲染中…")
    proc = subprocess.run(cmd, cwd=project_dir, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-12:])
        raise RuntimeError("ffmpeg 渲染失败（退出码 %d）：\n%s" % (proc.returncode, tail))

    project["render"] = {
        "status": "done",
        "output": out_path,
        "ffmpeg": pick_ffmpeg(),
        "quality": quality,
    }
    return out_path
