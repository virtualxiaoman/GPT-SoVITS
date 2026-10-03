# -*- coding: utf-8 -*-
"""GPT-SoVITS 语音合成 HTTP 服务：其他程序通过本机 HTTP 调用合成。

启动:
    python tts_server.py                  # 绑定 127.0.0.1:9881
    python tts_server.py -p 9000          # 换端口

接口（浏览器打开 http://127.0.0.1:9881/docs 可直接交互试用）:
    GET  /roles   可用角色列表
    POST /tts     {"role": "洛天依", "text": "你好呀", "lang": "zh", "speed": 1.0, "seed": -1}
                  （role 可省略，默认 洛天依）
                  成功返回 audio/wav 字节流；响应头 X-Wav-Path 为本地文件路径
                  （中文做了 URL 编码，Python 用 urllib.parse.unquote 还原）
    GET  /health  探活：{"status", "model_loaded", "busy"}

行为:
    * 启动后后台预加载模型；预加载完成前到达的请求会等待。
    * 所有合成请求经全局锁串行执行（GPU 推理是瓶颈），换角色时重载权重（数秒）。
    * 输出 wav 保存在 outputs/，启动时和之后每天自动清理超过 7 天的文件。
"""

import argparse
import os
import sys
import threading
import time
from contextlib import asynccontextmanager
from urllib.parse import quote

import tts_infer
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

CLEANUP_DAYS = 7
CLEANUP_INTERVAL = 24 * 3600
ALLOWED_LANGS = ("zh", "ja", "en", "ko", "yue", "auto")

_gpu_lock = threading.Lock()
_last_cleanup = 0.0


def _cleanup_old_outputs():
    out_dir = tts_infer.DEFAULT_OUT
    if not os.path.isdir(out_dir):
        return
    cutoff = time.time() - CLEANUP_DAYS * 86400
    removed = 0
    for fn in os.listdir(out_dir):
        if not fn.lower().endswith(".wav"):
            continue
        path = os.path.join(out_dir, fn)
        try:
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
                removed += 1
        except OSError:
            pass
    if removed:
        print("[server] 已清理 %d 个超过 %d 天的输出文件" % (removed, CLEANUP_DAYS))


def _maybe_cleanup():
    global _last_cleanup
    now = time.time()
    if now - _last_cleanup >= CLEANUP_INTERVAL:
        _last_cleanup = now
        _cleanup_old_outputs()


def _preload():
    try:
        with _gpu_lock:
            tts_infer._get_pipeline()
        print("[server] 模型预加载完成，可以开始合成")
    except Exception as e:
        # 不致命：首次请求时会再次尝试加载
        print("[server] 模型预加载失败: %r" % e)


@asynccontextmanager
async def _lifespan(_app):
    _cleanup_old_outputs()
    threading.Thread(target=_preload, daemon=True).start()
    yield


app = FastAPI(title="GPT-SoVITS TTS 服务", lifespan=_lifespan)


class TTSRequest(BaseModel):
    role: str = tts_infer.DEFAULT_ROLE
    text: str
    lang: str = "zh"
    speed: float = 1.0
    seed: int = -1


@app.get("/")
def index():
    return {"service": "GPT-SoVITS TTS", "endpoints": ["/roles", "/tts", "/health", "/docs"]}


@app.get("/roles")
def list_roles():
    return [
        {"name": name, "version": cfg.get("version", ""), "note": cfg.get("note", "")}
        for name, cfg in tts_infer.load_roles().items()
    ]


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model_loaded": tts_infer._pipeline is not None,
        "busy": _gpu_lock.locked(),
    }


@app.post("/tts")
def tts(req: TTSRequest):
    _maybe_cleanup()
    if not req.text.strip():
        raise HTTPException(400, "text 不能为空")
    if req.lang not in ALLOWED_LANGS:
        raise HTTPException(400, "不支持的语言: %s（可选: %s）" % (req.lang, "、".join(ALLOWED_LANGS)))
    roles = tts_infer.load_roles()
    if req.role not in roles:
        raise HTTPException(404, "未注册的角色: %s（可用: %s）" % (req.role, "、".join(roles)))

    try:
        with _gpu_lock:
            path = tts_infer.synthesize(
                req.role, req.text, lang=req.lang, speed_factor=req.speed, seed=req.seed
            )
            with open(path, "rb") as f:
                wav = f.read()
    except Exception as e:
        raise HTTPException(500, "合成失败: %r" % e)

    return Response(
        content=wav,
        media_type="audio/wav",
        headers={"X-Wav-Path": quote(path)},
    )


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="GPT-SoVITS 语音合成 HTTP 服务（本机调用）")
    parser.add_argument("-a", "--host", default="127.0.0.1", help="绑定地址（默认 127.0.0.1，仅本机可访问）")
    parser.add_argument("-p", "--port", type=int, default=9881, help="端口（默认 9881）")
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
