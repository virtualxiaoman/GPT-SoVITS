# -*- coding: utf-8 -*-
"""GPT-SoVITS 角色语音合成：输入「角色名 + 文本」，输出 wav 文件路径。

命令行:
    python tts_infer.py --list
    python tts_infer.py --role 星野 --text "先生、おはよう～" --lang ja
    python tts_infer.py --role 白子（二年级） --text "欢迎来到我的博客！" --lang zh

Python 调用:
    from tts_infer import synthesize
    wav_path = synthesize("爱丽丝", "欢迎来到我的博客！", lang="zh")

角色登记表在 characters/ 文件夹（每个角色一个 yaml），新增角色只需添加一个配置文件；
PyCharm 里点击运行请用 tts_run.py。

说明:
    * 模型保存在 G:\\Models\\GPT-SoVITS 原地使用，不拷贝进本仓库。
    * 参考音频必须为 3~10 秒（模型包自带的参考音频已按此筛选）。
    * 首次合成需加载模型（约 30~60 秒）；同角色连续合成很快，切换角色会重载权重。
    * tts_infer.yaml 中的路径是相对路径，因此本模块会将工作目录切换到仓库根目录
      （os.chdir），调用方若依赖当前目录请提前解析为绝对路径。
"""

import argparse
import os
import sys
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.join(REPO_ROOT, "outputs")
CHARACTERS_DIR = os.path.join(REPO_ROOT, "characters")

_pipeline = None
_loaded = {"gpt": None, "sovits": None}
_roles_cache = None


def load_roles():
    """读取 characters/ 下所有角色配置（*.yaml / *.yml），返回 {角色名: 配置}。

    角色名取配置文件里的 name 字段，缺省用文件名（不含扩展名）。
    必填字段：gpt、sovits、ref_audio；可选：prompt_text、prompt_lang、note、version。
    """
    global _roles_cache
    if _roles_cache is not None:
        return _roles_cache
    try:
        import yaml
    except ImportError:
        raise SystemExit("缺少 PyYAML：请在 GPTSoVits 环境里运行（conda activate GPTSoVits）")
    if not os.path.isdir(CHARACTERS_DIR):
        raise SystemExit("未找到角色配置目录: %s" % CHARACTERS_DIR)

    roles = {}
    for fn in sorted(os.listdir(CHARACTERS_DIR)):
        if not fn.lower().endswith((".yaml", ".yml")):
            continue
        with open(os.path.join(CHARACTERS_DIR, fn), encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        name = str(cfg.get("name") or os.path.splitext(fn)[0])
        for key in ("gpt", "sovits", "ref_audio"):
            if not cfg.get(key):
                raise SystemExit("角色配置 %s 缺少必填字段: %s" % (fn, key))
        cfg["name"] = name
        cfg.setdefault("prompt_text", "")
        cfg.setdefault("prompt_lang", "ja")
        roles[name] = cfg
    _roles_cache = roles
    return roles


def _get_pipeline():
    global _pipeline
    os.chdir(REPO_ROOT)
    if _pipeline is None:
        gsv_dir = os.path.join(REPO_ROOT, "GPT_SoVITS")
        for p in (REPO_ROOT, gsv_dir):
            if p not in sys.path:
                sys.path.append(p)
        from GPT_SoVITS.TTS_infer_pack.TTS import TTS, TTS_Config

        config_path = os.path.join(REPO_ROOT, "GPT_SoVITS", "configs", "tts_infer.yaml")
        _pipeline = TTS(TTS_Config(config_path))
    return _pipeline


def synthesize(role_name, target_text, lang="zh", out_dir=None, ref_audio=None,
               prompt_text=None, prompt_lang=None, speed_factor=1.0, seed=-1,):
    """合成语音并返回生成 wav 的绝对路径。

    role_name: characters/ 中登记的角色名，如 "星野"（用 load_roles() 可查全部）。
    target_text: 要合成的文本。
    lang: 文本语言，zh / ja / en / ko / yue。
    out_dir: 输出目录（默认 <仓库>/outputs）。
    ref_audio / prompt_text / prompt_lang: 覆盖该角色默认的参考音频及其文本、语言。
    """
    roles = load_roles()
    if role_name not in roles:
        raise KeyError("未注册的角色: %s，可用角色: %s" % (role_name, "、".join(roles)))
    role = roles[role_name]
    pipe = _get_pipeline()

    # 先切 SoVITS（它决定模型版本），再切 GPT
    if _loaded["sovits"] != role["sovits"]:
        print("[tts] 加载 SoVITS 权重: %s" % role["sovits"])
        pipe.init_vits_weights(role["sovits"])
        _loaded["sovits"] = role["sovits"]
    if _loaded["gpt"] != role["gpt"]:
        print("[tts] 加载 GPT 权重: %s" % role["gpt"])
        pipe.init_t2s_weights(role["gpt"])
        _loaded["gpt"] = role["gpt"]

    req = {
        "text": target_text,
        "text_lang": lang,
        "ref_audio_path": ref_audio or role["ref_audio"],
        "prompt_text": role["prompt_text"] if prompt_text is None else prompt_text,
        "prompt_lang": prompt_lang or role.get("prompt_lang", "ja"),
        "text_split_method": "cut5",
        "batch_size": 1,
        "speed_factor": speed_factor,
        "sample_steps": 32,
        "seed": seed,
        "parallel_infer": True,
        "repetition_penalty": 1.35,
    }
    sample_rate, audio = next(pipe.run(req))

    import soundfile as sf

    out_dir = out_dir or DEFAULT_OUT
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    out_path = os.path.join(out_dir, "%s_%s.wav" % (role_name, stamp))
    sf.write(out_path, audio, sample_rate)
    return os.path.abspath(out_path)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="GPT-SoVITS 角色语音合成：文本 + 角色名 -> wav 路径")
    parser.add_argument("--role", help="角色名，如 星野（用 --list 查看全部）")
    parser.add_argument("--text", help="要合成的文本")
    parser.add_argument("--lang", default="zh", help="文本语言: zh/ja/en/ko/yue（默认 zh）")
    parser.add_argument("--out", default=None, help="输出目录（默认 <仓库>/outputs）")
    parser.add_argument("--ref", default=None, help="覆盖默认参考音频路径")
    parser.add_argument("--ref-text", default=None, help="覆盖参考音频对应的文本")
    parser.add_argument("--ref-lang", default=None, help="参考音频语言（默认 ja）")
    parser.add_argument("--speed", type=float, default=1.0, help="语速（默认 1.0）")
    parser.add_argument("--seed", type=int, default=-1, help="随机种子，-1 为随机")
    parser.add_argument("--list", action="store_true", help="列出 characters/ 中登记的角色")
    args = parser.parse_args()

    if args.list:
        for name, role in load_roles().items():
            extra = "  [%s]" % role["note"] if role.get("note") else ""
            print("%s\t%s\t%s%s" % (name, role.get("version", ""), role["ref_audio"], extra))
        return

    if not args.role or not args.text:
        parser.error("需要 --role 和 --text（用 --list 查看可用角色）")

    out_path = synthesize(
        args.role,
        args.text,
        lang=args.lang,
        out_dir=args.out,
        ref_audio=args.ref,
        prompt_text=args.ref_text,
        prompt_lang=args.ref_lang,
        speed_factor=args.speed,
        seed=args.seed,
    )
    print(out_path)


if __name__ == "__main__":
    main()
