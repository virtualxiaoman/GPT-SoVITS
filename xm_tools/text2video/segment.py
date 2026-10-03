# -*- coding: utf-8 -*-
"""文本切句：把一段文本切成适合逐句配音和字幕的短句。

规则（阈值均可调）:
    1. 一级切分：句末标点（。！？!?；;… 及英文句号）之后断开，
       并吸收紧随的收尾符号（」』”"）】等）；
    2. 再切：超过 max_chars 的句子，在 ，、： 等标点处继续切开；没有标点则按长度硬切；
    3. 合并：短于 min_chars 的句子与相邻句合并（"很短的句子两小句一个字幕"），
       合并后总长不超过 merge_max；
    4. 字幕显示文本去掉句尾的 。，、；TTS 文本保留全部标点（标点影响语气）。

长度单位：1 个全角字符 = 1，1 个半角字符 = 0.5（空白不计）。

已知局限：英文缩写（Mr. 等）会被误判断句；换行会被当作空格处理。

对外接口:
    split_text(text, min_chars=5, max_chars=24, merge_max=14)
        -> [{"text": 配音文本, "subtitle_text": 字幕文本}, ...]
    subtitle_text_of(s) / display_len(s) / char_units(ch)
"""

import re
import unicodedata

_END = "。！？!?；;…"
_TAIL = "」』”\"'）)】〉》〕］"
_TRIM = "。，,、；; "
_ALL_PUNCT = "。，,、！？!?…；;"


def char_units(ch):
    """1 个全角字符记 1，半角记 0.5。"""
    return 1.0 if unicodedata.east_asian_width(ch) in ("W", "F") else 0.5


def display_len(s):
    """按「全角当 1、半角当 0.5」统计长度，空白不计。"""
    return sum(char_units(c) for c in s if not c.isspace())


def subtitle_text_of(s):
    """字幕显示文本：去掉句尾的 。，、等标点，保留 ！？… 和收尾引号。"""
    t = s.strip()
    tail = ""
    while t and t[-1] in _TAIL:
        tail = t[-1] + tail
        t = t[:-1]
    return (t.rstrip(_TRIM) + tail).strip()


def _is_dot_end(text, i):
    """英文句号：后面是空白或结尾才算句末（避免切 3.14 / Mr. 之类）。"""
    if text[i] != ".":
        return False
    return i + 1 >= len(text) or text[i + 1].isspace()


def _split_primary(text):
    """一级切分：按句末标点断句，保留标点与收尾引号。"""
    parts, buf = [], []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        buf.append(ch)
        if ch in _END or _is_dot_end(text, i):
            j = i + 1
            while j < n and (text[j] in _END or text[j] in _TAIL or _is_dot_end(text, j)):
                buf.append(text[j])
                j += 1
            parts.append("".join(buf))
            buf = []
            i = j
            continue
        i += 1
    if buf:
        parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def _hard_wrap(s, max_chars):
    """按长度均衡硬切成尽量均匀的几段（避免出现很小的尾巴）。"""
    if display_len(s) <= max_chars:
        return [s]
    total = display_len(s)
    n_parts = int(total // max_chars) + (1 if total % max_chars else 0)
    target = total / n_parts
    out, cur, cur_len = [], [], 0.0
    for ch in s:
        w = 0.0 if ch.isspace() else char_units(ch)
        if cur and len(out) < n_parts - 1 and cur_len + w > target:
            out.append("".join(cur).strip())
            cur, cur_len = [], 0.0
            if ch.isspace():
                continue
            w = char_units(ch)
        cur.append(ch)
        cur_len += w
    if cur:
        out.append("".join(cur).strip())
    return [x for x in out if x]


def _split_long(s, max_chars):
    """二级切分：超长句在逗号/顿号/冒号处切开（一小句一个字幕）；
    单个分句仍超长时按长度均衡硬切。"""
    if display_len(s) <= max_chars:
        return [s]
    chunks = []
    for p in re.split(r"(?<=[，、：,:])", s):
        p = p.strip()
        if not p:
            continue
        chunks.extend(_hard_wrap(p, max_chars))
    return chunks


def _content_len(s):
    """内容长度（用于判断"过短"）：去掉句尾全部标点后统计。"""
    return display_len(s.rstrip(_ALL_PUNCT))


def _merge_short(chunks, min_chars, merge_max):
    """过短的句子与相邻句合并，合并后不超过 merge_max。"""
    out = []
    for s in chunks:
        if (out and _content_len(out[-1]) < min_chars
                and _content_len(out[-1]) + _content_len(s) <= merge_max):
            out[-1] += s
        else:
            out.append(s)
    if (len(out) >= 2 and _content_len(out[-1]) < min_chars
            and _content_len(out[-2]) + _content_len(out[-1]) <= merge_max):
        last = out.pop()
        out[-1] += last
    return out


def _normalize(text):
    return re.sub(r"\s+", " ", text).strip()


def split_text(text, min_chars=5, max_chars=24, merge_max=14):
    """把文本切成适合逐句配音/字幕的短句。

    返回 [{"text": 配音文本（含标点）, "subtitle_text": 字幕显示文本}, ...]
    """
    if not text or not text.strip():
        return []
    text = _normalize(text)
    chunks = []
    for p in _split_primary(text):
        chunks.extend(_split_long(p, max_chars))
    chunks = [c.strip() for c in chunks if c.strip()]
    chunks = _merge_short(chunks, min_chars, merge_max)
    return [{"text": c, "subtitle_text": subtitle_text_of(c)} for c in chunks]
