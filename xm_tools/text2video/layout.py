# -*- coding: utf-8 -*-
"""时间轴排版：时长粗估、句间停顿分配、end_time 自动适配、不重叠校验。

时长分两级（见 docs/cn/plan-text2video.md 3.2）：
    * 合成前：estimate_duration() 按语速粗估；
    * 合成后：以每句 wav 的实测时长为准，替换 durations 后重新 plan_timing() 即可。
"""

from segment import display_len

# 粗估语速（字/秒，speed=1.0 时；长度单位见 segment.display_len）
_RATE = {"zh": 4.2, "ja": 5.5, "ko": 5.0, "yue": 4.2, "en": 13.0, "auto": 5.0}
_MIN_DUR = 0.3


def estimate_duration(text, lang="zh", speed=1.0):
    """按语速粗估一句语音的时长（秒）。合成后应以实测 wav 时长为准。"""
    rate = _RATE.get(lang, 5.0)
    return max(_MIN_DUR, display_len(text) / rate / max(speed, 0.1))


def plan_timing(durations, start_time=0.0, end_time=None, default_gap=0.3, min_gap=0.08):
    """给每句分配开始时间（秒）。

    end_time=None：用 default_gap 顺排，end_time 取最后一句的结束时间（fit="auto"）。
    给了 end_time：
        * 富余 -> 多余时间平均摊入句间停顿（fit="padded"）；
        * 不足 -> 先压缩停顿到 min_gap（fit="tight"）；仍放不下则按 min_gap 排并标记
          超时秒数（fit="overflow"），由调用方提示用户。
    """
    n = len(durations)
    if n == 0:
        raise ValueError("没有句子，无法排版")
    durations = [float(d) for d in durations]
    audio_sum = sum(durations)
    available = None if end_time is None else float(end_time) - float(start_time)
    if available is not None and available <= 0:
        raise ValueError("end_time(%.2fs) 必须大于 start_time(%.2fs)" % (end_time, start_time))

    if available is None:
        gap, fit = default_gap, "auto"
    elif n == 1:
        gap = 0.0
        fit = "padded" if durations[0] <= available + 1e-9 else "overflow"
    else:
        slack = available - (audio_sum + (n - 1) * default_gap)
        needed_min = audio_sum + (n - 1) * min_gap
        if slack >= 0:
            gap, fit = default_gap + slack / (n - 1), "padded"
        elif needed_min <= available + 1e-9:
            gap, fit = min_gap + (available - needed_min) / (n - 1), "tight"
        else:
            gap, fit = min_gap, "overflow"

    starts, t = [], float(start_time)
    for d in durations:
        starts.append(t)
        t += d + gap
    needed_min = audio_sum + (n - 1) * min_gap
    return {
        "starts": starts,
        "durations": durations,
        "start_time": float(start_time),
        "end_time": starts[-1] + durations[-1],
        "fit": fit,
        "gap": gap,
        "default_gap": default_gap,
        "min_gap": min_gap,
        "audio_sum": audio_sum,
        "needed_min": needed_min,
        "available": available,
        "overflow_seconds": max(0.0, needed_min - available) if available is not None else 0.0,
    }


def check_no_overlap(starts, durations, min_gap=0.08, tol=1e-6):
    """检查相邻句是否满足最小间隔。返回违规列表 [(前句序号, 后句序号, 差多少秒)]。"""
    bad = []
    for i in range(len(starts) - 1):
        g = starts[i + 1] - (starts[i] + durations[i])
        if g < min_gap - tol:
            bad.append((i + 1, i + 2, min_gap - g))
    return bad


def format_table(segments, plan):
    """把切句 + 排版结果排成表格文本（给运行脚本/CLI 打印用）。"""
    lines = [
        "    #    开始      结束     时长    字幕",
        "  ---  --------  --------  ------  ------------------------------",
    ]
    for i, (s, st, d) in enumerate(zip(segments, plan["starts"], plan["durations"]), 1):
        lines.append("  %3d  %6.2fs  %6.2fs  %5.2fs  %s"
                     % (i, st, st + d, d, s["subtitle_text"]))
    return "\n".join(lines)


def fit_summary(plan):
    """排版结论文字（一行）。"""
    n = len(plan["durations"])
    total = plan["end_time"] - plan["start_time"]
    fit = plan["fit"]
    if fit == "auto":
        return "总时长（自动估计）= %.2fs = 各句合计 %.2fs + 句间停顿 %.2fs" % (
            total, plan["audio_sum"], total - plan["audio_sum"])
    if fit == "padded":
        slack = plan["available"] - plan["audio_sum"] - (n - 1) * plan["default_gap"] if n > 1 else plan["available"] - plan["audio_sum"]
        if n == 1:
            return "end_time 富余 %.2fs（单句，未使用）" % slack
        return "总时长 %.2fs 内富余 %.2fs，已平均摊入句间停顿（实际间隔 %.2fs）" % (total, slack, plan["gap"])
    if fit == "tight":
        return "总时长 %.2fs：需求超出默认间隔方案，句间停顿已压缩到 %.2fs（最小 %.2fs）" % (
            total, plan["gap"], plan["min_gap"])
    target = plan["start_time"] + plan["available"]
    return "警告：按最小停顿 %.2fs 仍超出 end_time %.2fs（差 %.2fs）" % (
        plan["min_gap"], target, plan["overflow_seconds"])
