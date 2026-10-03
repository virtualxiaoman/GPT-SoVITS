# -*- coding: utf-8 -*-
"""PyCharm 点击运行入口：修改下面的变量，然后直接点运行（不需要命令行参数）。

角色名见 characters/ 文件夹（或运行 `python tts_infer.py --list`）。
输出的 wav 路径会打印在下方控制台，文件默认保存在 outputs/ 目录。
"""

# ======== 在这里修改 ========
ROLE = "洛天依"        # 角色名，如 洛天依 / 星野 / 爱丽丝 / 白子（二年级）
TEXT = "大家好，我是虚拟歌手洛天依"     # 要合成的文本
LANG = "zh"            # 文本语言: zh / ja / en / ko / yue
SPEED = 1.0            # 语速，1.0 为正常
# ==========================

if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from tts_infer import synthesize

    out_path = synthesize(ROLE, TEXT, lang=LANG, speed_factor=SPEED)
    print("生成完成：" + out_path)
