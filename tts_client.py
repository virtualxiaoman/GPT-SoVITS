# -*- coding: utf-8 -*-
"""tts_server.py 的调用方客户端（同一台机器）。

用法:
    from tts_client import synthesize

    wav_path = synthesize("星野", "おはよう～", lang="ja")   # 返回服务端生成的 wav 本地路径
    synthesize(text="你好呀")                                # 省略 role 时用默认角色（洛天依）
    synthesize("星野", "欢迎来到我的博客！", lang="zh", save_to="blog/hello.wav")  # 另存一份

    # 服务未启动时默认自动拉起；若要改为明确报错：
    synthesize("星野", "你好", autostart=False)   # 抛 RuntimeError，提示手动启动命令

可选环境变量（一般不用设）:
    TTS_SERVER_URL     服务地址，默认 http://127.0.0.1:9881
    TTS_PYTHON         自动拉起时使用的解释器，默认本机 GPTSoVits conda 环境
    TTS_SERVER_SCRIPT  tts_server.py 的路径，默认与本文件同目录（把本文件拷到别的项目用时需设置）
"""

import os
import subprocess
import sys
import tempfile
import time
import urllib.parse

import requests

BASE_URL = os.environ.get("TTS_SERVER_URL", "http://127.0.0.1:9881").rstrip("/")
DEFAULT_PYTHON = r"C:\Users\Administrator\.conda\envs\GPTSoVits\python.exe"
SERVER_SCRIPT = os.environ.get("TTS_SERVER_SCRIPT") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "tts_server.py"
)
AUTOSTART_LOG = os.path.join(tempfile.gettempdir(), "tts_server_autostart.log")

_START_HINT = (
    "TTS 服务未启动（%s）。手动启动：在 GPT-SoVITS 仓库目录运行 `python tts_server.py`，"
    "或调用 synthesize 时使用 autostart=True 自动拉起。" % BASE_URL
)


def check_service():
    """服务在跑返回 /health 的 dict，未启动返回 None。"""
    try:
        r = requests.get(BASE_URL + "/health", timeout=2)
        return r.json() if r.status_code == 200 else None
    except (requests.exceptions.RequestException, ValueError):
        return None


def _start_and_wait(wait_s=90):
    python = os.environ.get("TTS_PYTHON") or DEFAULT_PYTHON
    if not os.path.exists(python):
        python = sys.executable

    log = open(AUTOSTART_LOG, "ab")
    log.write(
        ("\n=== %s 自动拉起服务: %s ===\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), SERVER_SCRIPT)).encode("utf-8")
    )
    log.flush()
    url = urllib.parse.urlsplit(BASE_URL)
    proc = subprocess.Popen(
        [python, SERVER_SCRIPT, "-a", url.hostname or "127.0.0.1", "-p", str(url.port or 9881)],
        cwd=os.path.dirname(os.path.abspath(SERVER_SCRIPT)),
        stdout=log,
        stderr=log,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    log.close()

    deadline = time.time() + wait_s
    while time.time() < deadline:
        if check_service() is not None:
            return
        if proc.poll() is not None:
            # 并发拉起时另一个实例可能已占住端口，给健康检查留出时间
            for _ in range(10):
                time.sleep(1)
                if check_service() is not None:
                    return
            raise RuntimeError("TTS 服务启动失败（进程退出，端口可能被占用）。日志: %s" % AUTOSTART_LOG)
        time.sleep(1)
    raise RuntimeError("等待 TTS 服务就绪超时（%d 秒）。日志: %s" % (wait_s, AUTOSTART_LOG))


def synthesize(role="洛天依", text="", lang="zh", speed=1.0, seed=-1, save_to=None, autostart=True, timeout=300):
    """调用 TTS 服务合成语音，返回服务端 wav 的本地路径（同机可直接使用）。

    role 默认 洛天依；text 必填；lang 可选 zh/ja/en/ko/yue/auto。
    save_to 给定时把音频另存一份到该路径；服务未启动时默认自动拉起。
    """
    if check_service() is None:
        if not autostart:
            raise RuntimeError(_START_HINT)
        _start_and_wait()

    try:
        r = requests.post(
            BASE_URL + "/tts",
            json={"role": role, "text": text, "lang": lang, "speed": speed, "seed": seed},
            timeout=(5, timeout),
        )
    except requests.exceptions.RequestException as e:
        raise RuntimeError("请求 TTS 服务失败（%s）: %s" % (BASE_URL, e))

    if r.status_code != 200:
        try:
            detail = r.json().get("detail", r.text)
        except ValueError:
            detail = r.text
        raise RuntimeError("TTS 合成失败 (HTTP %d): %s" % (r.status_code, detail))

    wav_path = urllib.parse.unquote(r.headers.get("X-Wav-Path", ""))
    if save_to:
        os.makedirs(os.path.dirname(os.path.abspath(save_to)), exist_ok=True)
        with open(save_to, "wb") as f:
            f.write(r.content)
    return wav_path
