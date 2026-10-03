# GPT-SoVITS 使用指南（Windows 11 + RTX 5080）

> 本指南针对当前这台机器编写：Windows 11 + RTX 5080（16 GB 显存）。
> 项目位置：`G:\Projects\github\GPT-SoVITS`（官方源码仓库，非整合包）
> 模型位置：`G:\Models\GPT-SoVITS`（已训练好的蔚蓝档案角色模型）
>
> **目标：输入「文本 + 角色名」，输出语音文件路径。**

完成后的最终使用方式（装环境只需一次）：

```powershell
conda activate GPTSoVits
cd G:\Projects\github\GPT-SoVITS
python tts_infer.py --role 星野 --text "欢迎来到我的博客！" --lang zh
# 最后一行输出：G:\Projects\github\GPT-SoVITS\outputs\星野_20261003_143012_456.wav
```

---

## 0. 总览

| 步骤 | 做什么 | 一次性? |
|---|---|---|
| 第 1 步 | 准备 conda（这台机器已装 Anaconda，直接用） | 是 |
| 第 2 步 | 创建 Python 3.10 环境，运行 `install.ps1` 装依赖 + 底模 | 是 |
| 第 3 步 | 验证 GPU 可用 | 是 |
| 第 4 步 | 解压 满 / 爱丽丝 的参考音频包 | 是 |
| 第 5 步 | 用 `tts_infer.py`（命令行）或 `tts_run.py`（PyCharm 点击运行）合成 | 每次使用 |

> **RTX 5080 注意事项**：5080 是 Blackwell 架构（sm_120），必须使用 **CU128** 版 PyTorch（`install.ps1 -Device CU128`）。装 CU126/CPU 版会报 `no kernel image is available` 或直接跑在 CPU 上。
>
> **不想用 conda？** 可完全绕开它，见文末「附录 A：不用 conda 的替代方案（venv 路线）」。

---

## 1. 准备 conda（这台机器已有 Anaconda，直接用）

这台机器已经安装了 **Anaconda**（`D:\Softwares\Coding\Anaconda`，conda 26.1.1），**不需要再装 Miniconda** —— 两者提供的 `conda` 是同一个工具，Miniconda 只是不含预置包的轻量安装版。

目前唯一的问题是：这个 Anaconda 安装**没有加入 PATH**，在普通 PowerShell/cmd 里直接敲 `conda` 会提示找不到命令。任选一种方式解决：

1. **最简单**：开始菜单搜索并打开 **Anaconda Prompt**（它的 PATH 已配好），之后第 2 步的所有命令都在这个窗口里执行；
2. 或执行一次 `conda init`，之后**重开终端**即可直接用 `conda`：
   ```powershell
   & "D:\Softwares\Coding\Anaconda\Scripts\conda.exe" init powershell
   ```
   （平时用 cmd 的话把 `powershell` 换成 `cmd.exe`）；
3. 或把 `D:\Softwares\Coding\Anaconda\condabin` 加入系统 PATH（Anaconda 官方推荐只加这个目录）。

验证（预期输出 `conda 26.1.1`）：

```powershell
conda --version
```

> 以后换一台没有 conda 的机器时，再安装 Miniconda 即可：`winget install -e --id Anaconda.Miniconda3`。

---

## 2. 创建环境并安装依赖（一次性，耗时最长）

### 2.1 创建 Python 3.10 环境

以下命令在**已激活 conda 的终端**（Anaconda Prompt，或按第 1 步 `conda init` 过的终端）里执行。官方要求 Python 3.10（机器上已有的 3.12 / 3.14 不在官方支持范围内，不要使用）。

```powershell
conda create -n GPTSoVits python=3.10 -y
conda activate GPTSoVits
```

> **国内网络必读**：直连 Anaconda 官方源（repo.anaconda.com）容易下载中断（报错特征 `Connection broken: IncompleteRead`），会导致环境创建失败——此时 `conda activate` 会提示 `EnvironmentNameNotFound`（因为创建根本没完成，conda 已自动清理残留目录，直接重跑即可）。
> 本机已配好清华镜像 + 严格频道优先级（`C:\Users\Administrator\.condarc`，2026-10-03 配置并验证生效），无需再操作。换机器时请先写如下 `.condarc` 再执行创建：
> ```yaml
> channels:
>   - defaults
> show_channel_urls: true
> channel_priority: strict
> default_channels:
>   - https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main
>   - https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/r
>   - https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/msys2
> custom_channels:
>   conda-forge: https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud
> ```
> `channel_priority: strict` 必须加：否则 defaults 与 conda-forge 的包会混装（如 anaconda 源的 libglib 配上 conda-forge 的 gdk-pixbuf），ABI 不兼容导致安装 ffmpeg 时的链接错误（详见第 9 节排查表）。

### 2.2 运行官方安装脚本

脚本内部会调用 `conda` 和 `pip`，务必在 conda 可用的终端里运行，并先确认环境已激活（`python` 指向 conda 环境而不是系统 Python）：

```powershell
python -c "import sys; print(sys.prefix)"   # 应指向 conda 环境目录（本机实际为 C:\Users\Administrator\.conda\envs\GPTSoVits）
```

然后执行：

```powershell
cd G:\Projects\github\GPT-SoVITS
powershell -ExecutionPolicy Bypass -File install.ps1 -Device CU128 -Source ModelScope
```

参数说明：
- `-Device CU128`：RTX 5080 必须选这个（不要选 CU126/CPU）；
- `-Source ModelScope`：从魔搭下载底模（国内快）；也可换 `HF-Mirror`（HuggingFace 镜像）；海外网络可用 `HF`；
- 不需要 `-DownloadUVR5`（人声分离，与本需求无关）。

安装脚本会自动完成（约几十分钟，取决于网速）：

| 内容 | 用途 |
|---|---|
| ffmpeg、cmake（conda-forge） | 音频处理 |
| PyTorch + torchcodec（cu128 版） | GPU 推理核心 |
| requirements.txt 全部依赖 | 运行环境 |
| `pretrained_models.zip`（约数 GB） | **底模**：chinese-hubert-base、chinese-roberta-wwm-ext-large、s1v3.ckpt、v2Pro/s2Gv2ProPlus.pth 等 |
| G2PWModel | 中文多音字注音 |
| nltk_data、open_jtalk 词典 | 日语文本处理 |

### 2.3 验证 GPU

```powershell
python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

期望输出类似：

```
2.7.x+cu128 True NVIDIA GeForce RTX 5080
```

若 `cuda.is_available()` 为 `False` 或版本号里没有 `+cu128`，重新执行 2.2 节（切换 `-Source` 重跑即可，已下载的部分会跳过）。

---

## 3. 认识模型包（不用改动，直接原地使用）

模型包 `G:\Models\GPT-SoVITS` 的结构（已逐个核对）：

- 每个角色一个文件夹；模型 = **GPT 权重（.ckpt） + SoVITS 权重（.pth）**，两者必须同一角色配套使用；
- `参考音频`：推理时的音色参考，**必须 3~10 秒**（推理代码会硬性校验），建议 5~8 秒；
- `参考文本.txt` / `all.txt`：参考音频的配套文本，格式为 `路径|说话人|语言|文本`，按文件名查找；
- `原音频留档`、`角色名_日期.zip`、`wiki.txt` 是训练素材，**推理用不到**；
- v2 与 v2ProPlus 是两代模型主干，程序会**自动识别**（读文件头），你不需要做任何转换。

### 各角色 → 文件对照表

下表为 `tts_infer.py` 中已登记的角色（文件名中的数字是训练轮次，`-e15`/`e16`/`e18`/`e24` 为最后一版；想换轮次改路径即可）：

| 角色 | 版本 | GPT 权重（相对 `G:\Models\GPT-SoVITS\`） | SoVITS 权重 | 默认参考音频（时长） |
|---|---|---|---|---|
| 星野 | v2 | 星野\日配数据集制\成品模型\GPT_weights_v2\Hoshino-e15.ckpt | 星野\日配数据集制\成品模型\SoVITS_weights_v2\Hoshino_e16_s576.pth | 星野\日配数据集制\参考音频\Hoshino_Victory.wav（8.0s） |
| 普拉娜 | v2 | 普拉娜\日配数据集制\成品模型\GPT_weights_v2\Plana-e15.ckpt | 普拉娜\日配数据集制\成品模型\SoVITS_weights_v2\Plana_e16_s208.pth | 普拉娜\日配数据集制\参考音频\New_NP0035_Work_Talk_3.wav（7.5s） |
| 梓 | v2 | 梓\日配数据集制\成品模型\GPT_weights_v2\Zi_BaiZhou-e15.ckpt | 梓\日配数据集制\成品模型\SoVITS_weights_v2\Zi_BaiZhou_e16_s256.pth | 梓\日配数据集制\参考音频\Azusa_LogIn_1.wav（7.5s） |
| 满 | v2ProPlus | 满\GPT_weights_v2ProPlus\Man-e15.ckpt | 满\SoVITS_weights_v2ProPlus\Man_e18_s306.pth | 满\all\ch0296_eventlogin_2.wav（8.1s，需先解压） |
| 爱丽丝 | v2ProPlus | 爱丽丝\GPT_weights_v2ProPlus\AiLiSi-e15.ckpt | 爱丽丝\SoVITS_weights_v2ProPlus\AiLiSi_e18_s486.pth | 爱丽丝\all\CH0200_Relationship_Up_2.wav（8.3s，需先解压） |
| 白子（三年级） | v2 | 白子（三年级）\成品模型\GPT_weights_v2\BaiZi_grade_three-e15.ckpt | 白子（三年级）\成品模型\SoVITS_weights_v2\BaiZi_grade_three_e24_s360.pth | 白子（三年级）\参考音频\all\CH0263_Gachaget.wav（6.7s） |
| 白子（二年级） | v2 | 白子（二年级）\日配数据集制\成品模型\GPT_weights_v2\Shiroko-e15.ckpt | 白子（二年级）\日配数据集制\成品模型\SoVITS_weights_v2\Shiroko_e16_s480.pth | 白子（二年级）\日配数据集制\参考音频\Shiroko_Gachaget.wav（8.3s） |
| 美游 | v2 | 美游\日配数据集制\成品模型\GPT_weights_v2\Miyu-e15.ckpt | 美游\日配数据集制\成品模型\SoVITS_weights_v2\Miyu_e16_s256.pth | 美游\日配数据集制\参考音频\CH0218_Season_Halloween.wav（8.3s） |
| 阿罗娜（日配） | v2 | 阿罗娜\日配数据集制\成品模型\GPT_weights_v2\ALuoNa-e15.ckpt | 阿罗娜\日配数据集制\成品模型\SoVITS_weights_v2\ALuoNa_e16_s224.pth | 阿罗娜\日配数据集制\参考音频\Arona_AttendanceEvent13_Enter_2.wav（6.8s） |
| 阿罗娜（中配） | v2 | 阿罗娜\中配数据集制\成品模型\GPT_weights_v2\ALuoNa_cn-e15.ckpt | 阿罗娜\中配数据集制\成品模型\SoVITS_weights_v2\ALuoNa_cn_e16_s256.pth | 阿罗娜\中配数据集制\参考音频\arona_work_talk_3.wav（5.8s，无参考文本） |

> 阿罗娜（中配）的数据集没有附带参考文本文件，脚本对该角色默认启用「无参考文本模式」（适当保持参考音频短一些即可）。其余角色均已从各自的 `参考文本.txt` / `all.txt` 中提取好默认参考文本。

---

## 4. 解压 满 / 爱丽丝 的参考音频（一次性）

这两个角色的参考音频打包在 `all.zip` 里（其余角色已解压好）：

```powershell
Expand-Archive -Path "G:\Models\GPT-SoVITS\满\all.zip"     -DestinationPath "G:\Models\GPT-SoVITS\满"
Expand-Archive -Path "G:\Models\GPT-SoVITS\爱丽丝\all.zip" -DestinationPath "G:\Models\GPT-SoVITS\爱丽丝"
```

解压后应存在：`G:\Models\GPT-SoVITS\满\all\ch0296_eventlogin_2.wav` 等文件。

---

## 5. 合成语音：文本 + 角色名 → wav 路径（主用法）

合成入口有两个：`tts_infer.py`（命令行 / Python 导入）和 `tts_run.py`（PyCharm 里点击运行）。**角色登记表在仓库根目录 `characters\` 文件夹里**，每个角色一个 yaml 配置文件，新增角色只需添加文件、不用改代码。

### 5.1 命令行

```powershell
conda activate GPTSoVits
cd G:\Projects\github\GPT-SoVITS

# 查看已登记的角色
python tts_infer.py --list

# 日语合成
python tts_infer.py --role 星野 --text "先生、おはよう～" --lang ja

# 中文合成
python tts_infer.py --role 白子（二年级） --text "欢迎来到我的博客！" --lang zh
```

成功时最后一行就是生成的 wav 绝对路径：

```
G:\Projects\github\GPT-SoVITS\outputs\白子（二年级）_20261003_143012_456.wav
```

- 首次运行需加载模型，约 30~60 秒（属正常）；
- 同一角色连续合成很快；**切换角色**会重新加载权重（几秒）；
- 输出目录默认 `G:\Projects\github\GPT-SoVITS\outputs\`，可用 `--out D:\audio` 修改。

### 5.2 PyCharm 点击运行

先把项目解释器配成 GPTSoVits 环境（File → Settings → Project → Python Interpreter → 选 `C:\Users\Administrator\.conda\envs\GPTSoVits\python.exe`），然后：

1. 打开 `tts_run.py`，修改顶部三个变量：

   ```python
   ROLE = "星野"          # 角色名（见 characters/ 或 python tts_infer.py --list）
   TEXT = "我喜欢你！"     # 要合成的文本
   LANG = "zh"            # 文本语言: zh / ja / en / ko / yue
   ```

2. 右键 → **Run 'tts_run'**（或点绿色三角运行）；
3. 控制台最后一行「生成完成：…」就是 wav 路径。

### 5.3 在 Python 代码里调用

```python
import sys
sys.path.insert(0, r"G:\Projects\github\GPT-SoVITS")

from tts_infer import synthesize

wav_path = synthesize("爱丽丝", "欢迎来到我的博客！", lang="zh")
print(wav_path)  # -> ...\outputs\爱丽丝_20261003_150000_123.wav
```

注意：
- `synthesize()` 会把进程工作目录切换（`chdir`）到仓库根目录（模型配置用的是相对路径），调用方如有依赖当前目录的逻辑请提前转成绝对路径；
- 单进程内串行调用即可；博客后端并发场景建议走第 7 步的 HTTP API。

### 5.4 换参考音频（可选调音色）

任何 3~10 秒的该角色音频都能当参考。用文件名到 `参考文本.txt` / `all.txt` 里查对应文本，然后覆盖：

```powershell
python tts_infer.py --role 星野 --text "今天的巡逻也拜托了" --lang zh `
  --ref "G:\Models\GPT-SoVITS\星野\日配数据集制\参考音频\CH0258_Lobby_2.wav" `
  --ref-text "糖分は大事だからね～アメは持ち歩いてるんだ～先生も一つ、要る？"
```

（以上为 PowerShell 换行写法；`--ref-text` 必须与参考音频内容一致，否则音色/语气会漂。）

### 5.5 新增角色（以后别人给你新模型时）

在 `characters\` 文件夹里复制任意一个 yaml（例如 `星野.yaml`），改成新角色的内容即可：

- 文件名 = 角色名（如 `新角色.yaml`）；加不加 `name` 字段都行，缺省用文件名；
- 必填 3 项：`gpt`、`sovits`（两个权重文件路径）、`ref_audio`（3~10 秒参考音频路径）；
- 可选：`prompt_text`（参考音频对应文本；没有就留空 `''` 启用无参考文本模式）、`prompt_lang`（默认 `ja`）、`note`（备注，会显示在 `--list` 结果里）、`version`（仅供查看）。

保存后运行 `python tts_infer.py --list` 会立刻列出新角色。

---

## 6.（可选）用 WebUI 手动验证一次

想眼见为实地跑一遍图形界面：

```powershell
conda activate GPTSoVits
cd G:\Projects\github\GPT-SoVITS

# 1) WebUI 的模型下拉框只扫描仓库内固定名称的文件夹，先把要试的角色权重复制进来（以星野为例）
New-Item -ItemType Directory -Force GPT_weights_v2, SoVITS_weights_v2 | Out-Null
Copy-Item "G:\Models\GPT-SoVITS\星野\日配数据集制\成品模型\GPT_weights_v2\Hoshino-e15.ckpt" GPT_weights_v2\
Copy-Item "G:\Models\GPT-SoVITS\星野\日配数据集制\成品模型\SoVITS_weights_v2\Hoshino_e16_s576.pth" SoVITS_weights_v2\

# 2) 启动
python webui.py zh_CN
```

浏览器打开 `http://127.0.0.1:9874`：
1. 进入 **1C-推理** 页签，点「刷新模型路径」，GPT 模型列表选 `Hoshino-e15.ckpt`，SoVITS 模型列表选 `Hoshino_e16_s576.pth`；
2. 点「开启推理」，会自动打开推理页面 `http://127.0.0.1:9872`；
3. 上传参考音频（拖入 `Hoshino_Victory.wav`），「参考音频的文本」粘贴 `おー、勝った勝った、先生、次も適度に頑張るから、よろしくねー。`，「参考音频的语种」选 `日文`；
4. 「需要合成的文本」输入内容（例如 `先生、おはよう～`），语种对应选择，点合成。

> 注意：`go-webui.bat` / `go-webui.ps1` 是给官方整合包用的（依赖 `runtime\` 目录），源码安装方式请用 `python webui.py zh_CN`。
> 这一步仅用于验证；`tts_infer.py` 直接读绝对路径，**不需要**复制权重文件。

---

## 7.（可选）HTTP API：给博客后端当服务用

保持一个服务常驻，用 HTTP 调用（适合博客/其他程序集成）：

```powershell
conda activate GPTSoVits
cd G:\Projects\github\GPT-SoVITS
python api_v2.py -a 127.0.0.1 -p 9880 -c GPT_SoVITS/configs/tts_infer.yaml
```

客户端示例（保存音频并拿到路径）：

```python
import requests

API = "http://127.0.0.1:9880"
ROLES = {
    "星野": {
        "gpt": r"G:\Models\GPT-SoVITS\星野\日配数据集制\成品模型\GPT_weights_v2\Hoshino-e15.ckpt",
        "sovits": r"G:\Models\GPT-SoVITS\星野\日配数据集制\成品模型\SoVITS_weights_v2\Hoshino_e16_s576.pth",
        "ref_audio": r"G:\Models\GPT-SoVITS\星野\日配数据集制\参考音频\Hoshino_Victory.wav",
        "prompt_text": "おー、勝った勝った、先生、次も適度に頑張るから、よろしくねー。",
        "prompt_lang": "ja",
    },
    # 其余角色同 tts_infer.py 的 ROLES
}
_current = {"role": None}

def synth(role: str, text: str, lang: str = "zh", out: str = "out.wav") -> str:
    cfg = ROLES[role]
    if _current["role"] != role:  # 切换角色才需要重新加载权重
        for ep, key in (("set_gpt_weights", "gpt"), ("set_sovits_weights", "sovits")):
            r = requests.get(f"{API}/{ep}", params={"weights_path": cfg[key]}, timeout=300)
            r.raise_for_status()
        _current["role"] = role
    r = requests.post(f"{API}/tts", json={
        "text": text,
        "text_lang": lang,
        "ref_audio_path": cfg["ref_audio"],
        "prompt_text": cfg["prompt_text"],
        "prompt_lang": cfg["prompt_lang"],
        "media_type": "wav",           # 返回 wav 二进制
    }, timeout=600)
    r.raise_for_status()
    with open(out, "wb") as f:
        f.write(r.content)
    return out
```

要点：
- `/tts` 直接返回音频二进制（HTTP 200），失败返回带错误信息的 JSON（HTTP 400）；
- 切换角色是**服务端全局状态**（两个 `set_*_weights` 接口），并发调用不同角色会互相干扰，建议固定角色或串行；
- 长文本把 `timeout` 调大即可，文本会自动切分（`text_split_method=cut5`）。

---

## 8. 参数与效果速查

| 项 | 说明 |
|---|---|
| 参考音频 | 硬性 3~10 秒；同说话人；5~8 秒更稳；换文件必须同步换 `--ref-text` |
| `--lang` | `zh` / `ja` / `en` / `ko` / `yue`；这批模型是日语数据微调，**日语最稳**，中文可用但可能带轻微日语口音；中日混排可试 `auto` |
| `--speed` | 语速，0.9~1.1 较自然 |
| 长文本 | 自动按标点切分，无需手动分段；整段合成后拼接为一个 wav |
| 音质发闷/电流声 | 把 `GPT_SoVITS/configs/tts_infer.yaml` 里 `custom` 段的 `is_half` 改为 `false`（质量优先），改完重跑 |
| 显存 | 16 GB 完全够用；若报显存不足（少见），先关闭其他占 GPU 的程序 |
| 复现同一段音频 | 加 `--seed 12345`，同文本 + 同参考 + 同种子结果一致 |

> 运行后 `GPT_SoVITS/configs/tts_infer.yaml` 的 `custom` 段会被自动更新为最近一次使用的权重路径与版本，这是程序的正常行为，无需干预（首次安装时的默认值是底模）。

---

## 9. 常见问题排查

| 现象 | 原因 / 解决 |
|---|---|
| `torch.cuda.is_available()` 返回 False | 装成了 CPU/CU126 版；`pip show torch` 看版本，重跑 `install.ps1 -Device CU128` |
| 报错含 `no kernel image is available` | 同上，5080（sm_120）必须用 cu128 版 torch |
| 装 PyTorch 时报 `Could not find a version that satisfies the requirement torchcodec` | PyTorch 官方索引（`download.pytorch.org/whl/cuXXX`）只提供 Linux 版 torchcodec，Windows 上从该索引永远找不到。解决：先从 PyPI 单独装**与 torch 版本配套**的 torchcodec（对照官方兼容表：torch≥2.11 ↔ torchcodec 0.12~0.15；本机 torch 为 2.11.0+cu128，对应 torchcodec 0.15.0，已装好），再重跑 `install.ps1`——torchcodec 已满足会被跳过，torch 正常从官方索引安装。torchcodec 是 torchaudio 读取音频的后端（合成时处理参考音频要用），不能省略。换机器时先看 `pip show torch`，再装对应版本的 torchcodec |
| 装 Python 依赖时报 `subprocess-exited-with-error`（构建阶段失败，常见于 `opencc`/`pyopenjtalk`） | conda 环境自带的 cmake 版本过旧（3.31 不认识 VS 2026 的生成器）。解决：`conda install -n GPTSoVits -c conda-forge "cmake>=4.4"` 升级（本机已升到 4.4.3）后重跑 |
| `OSError: 参考音频在3~10秒范围外，请更换！` | 换一个 3~10 秒的音频；用 ffmpeg 裁剪：`ffmpeg -i 输入.wav -ss 0 -t 6 输出.wav`（ffmpeg 已随环境装好） |
| 报某底模文件缺失（如 `s2Gv2ProPlus.pth`） | `pretrained_models` 没下载完整，重跑 `install.ps1`（可换 `-Source`） |
| pip 安装时报 C++ 编译错误（报错含 `cl`/`gcc`/`meson`/`cmake` 等关键字） | `pyopenjtalk`、`opencc` 在 Windows 上需源码编译；本机已装 VS 生成工具 2026（含 C++ 工具链，`D:\Softwares\Coding\Microsoft Visual Studio\18\BuildTools`），无需处理。换机器报错时安装 [VS Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) 并勾选「使用 C++ 的桌面开发」后重试 |
| `conda` 不是可用命令 | 本机 Anaconda 装在 `D:\Softwares\Coding\Anaconda` 但未加入 PATH：用开始菜单的 **Anaconda Prompt**，或执行 `& "D:\Softwares\Coding\Anaconda\Scripts\conda.exe" init powershell` 后重开终端 |
| `conda create` 报 `Connection broken`/`IncompleteRead`，随后 `conda activate` 提示 `EnvironmentNameNotFound` | 直连官方源下载中断导致创建失败（conda 会自动清理残留）：先按 2.1 节配置清华镜像，再重跑 `conda create -n GPTSoVits python=3.10 -y` |
| 装 ffmpeg 时报 `An error occurred while installing package 'conda-forge::gdk-pixbuf-...'` 或 `librsvg: The post-link script did not complete` | defaults 与 conda-forge 两个频道的包混装（如 anaconda 的 libglib 配 conda-forge 的 gdk-pixbuf），DLL 加载失败。解决：确保 `.condarc` 里有 `channel_priority: strict`（本机已配），再重装 |
| 上述报错后 `conda activate` 又提示 `EnvironmentNameNotFound` | 本机 conda 26.1.1 实测行为：**失败的事务回滚会删掉环境的 `conda-meta\history`**，环境被判定无效。修复：删除 `C:\Users\Administrator\.conda\envs\GPTSoVits` 整个目录后重新 `conda create`（环境里若已有大量 pip 包，重建前先确认无重要内容） |
| 下载底模/依赖很慢 | 换 `-Source ModelScope` 重跑；pip 慢可 `pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple` |
| 切换角色后音色不对 | 确认 GPT 和 SoVITS 权重来自**同一角色同一版本目录** |
| WebUI 模型列表为空 | 下拉框只扫仓库内 `GPT_weights_v2`、`SoVITS_weights_v2`、`GPT_weights_v2ProPlus`… 这些固定名称的文件夹（见 `config.py`），确认文件放在这些目录里并点了「刷新模型路径」 |
| 合成出空白/哑音 | 文本为空、或语言与实际文本不符；重新指定 `--lang` |
| 首次运行很慢 | 正常现象（加载底座 + 权重，约 30~60 秒），之后同角色调用很快 |

---

## 10. 目录与文件速查

| 用途 | 位置 |
|---|---|
| 输入模型（只读使用，不要改动） | `G:\Models\GPT-SoVITS\<角色>\...` |
| 合成入口 | `tts_infer.py`（命令行 / Python 导入）、`tts_run.py`（PyCharm 点击运行） |
| 角色登记表 | `characters\`（每个角色一个 yaml，新增角色 = 加一个文件） |
| 输出音频 | `G:\Projects\github\GPT-SoVITS\outputs\角色_时间戳.wav`（建议在 `.gitignore` 里加一行 `outputs/`） |
| 推理配置（设备/半精度/默认权重） | `GPT_SoVITS\configs\tts_infer.yaml` |
| 启动 WebUI | `python webui.py zh_CN`（主界面 <http://127.0.0.1:9874>，推理界面 9872） |
| 启动 HTTP API | `python api_v2.py -a 127.0.0.1 -p 9880` |

## 11. 模型使用须知（模型作者原文要点）

模型来自 B 站作者分享（模型包内 `A使用须知`）：**完全免费，仅供学习交流使用，禁止用于商业用途，禁止用于违反法律法规等用途**；二创使用时欢迎标明出处（<https://space.bilibili.com/523537077>）。生成音频涉及角色与声优权益，公开发布前请自行确认合规性。

---

## 附录 A：不用 conda 的替代方案（venv 路线）

conda 不是必须的——它只是官方 `install.ps1` 用来「建 Python 环境 + 装 ffmpeg/cmake」的工具。完全绕开 conda、用标准 `venv` 也能装出**一模一样**的运行环境（同一套 pip 包、同一个 cu128 torch）。缺点是官方脚本不能直接用，需要手动执行下面 5 组命令，且以后官方脚本更新时不会自动同步。

> 前置情况（本机已满足，无需操作）：Windows 上有两个包必须源码编译——`pyopenjtalk` 和 `opencc`。本机已装 VS 生成工具 2026（含 C++ 工具链），我已实测这两个包用纯 pip 都能编译通过。

### A.1 安装 Python 3.10

官方要求 3.10（本机现有 3.12 / 3.14 请勿使用）。

```powershell
winget install -e --id Python.Python.3.10
```

装完**另开一个终端**验证：

```powershell
py -3.10 --version
```

### A.2 创建并激活 venv

```powershell
cd G:\Projects\github\GPT-SoVITS
py -3.10 -m venv venv
.\venv\Scripts\Activate.ps1
```

若 PowerShell 提示「禁止运行脚本」，先执行一次 `Set-ExecutionPolicy -Scope Process Bypass`（只影响当前窗口）；cmd 用户改用 `venv\Scripts\activate.bat`。

### A.3 安装 ffmpeg

```powershell
winget install -e --id Gyan.FFmpeg
```

装完重开终端，`ffmpeg -version` 能输出即可。或者按官方手动安装文档，把 `ffmpeg.exe`、`ffprobe.exe` 下载后放到仓库根目录。

（说明：核心的 wav → wav 推理不直接调用 ffmpeg 二进制，但 WebUI 音频预处理、切片等功能会用到，建议装上。）

### A.4 安装 PyTorch（cu128）与项目依赖

```powershell
pip install torch torchcodec --index-url https://download.pytorch.org/whl/cu128
pip install -r extra-req.txt --no-deps
pip install -r requirements.txt
```

- `requirements.txt` 第一行强制 `opencc` 源码编译；`opencc`、`pyopenjtalk` 的构建脚本会让 pip 自动装好 cmake，本机编译器已就绪，直接跑即可（合计几分钟）；
- 若这一步出现 C++ 编译错误，说明缺编译工具链：安装 [VS Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/)，勾选「使用 C++ 的桌面开发」后重试。

### A.5 手动下载底模与词典（等价于 install.ps1 的下载步骤）

```powershell
# 在仓库根目录执行；以 ModelScope 为例（慢就换成 hf-mirror：
# 把 $Base 改为 "https://hf-mirror.com/XXXXRT/GPT-SoVITS-Pretrained/resolve/main"）
$Base = "https://www.modelscope.cn/models/XXXXRT/GPT-SoVITS-Pretrained/resolve/master"

Invoke-WebRequest "$Base/pretrained_models.zip" -OutFile pretrained_models.zip
Expand-Archive pretrained_models.zip -DestinationPath GPT_SoVITS -Force
Remove-Item pretrained_models.zip

Invoke-WebRequest "$Base/G2PWModel.zip" -OutFile G2PWModel.zip
Expand-Archive G2PWModel.zip -DestinationPath GPT_SoVITS\text -Force
Remove-Item G2PWModel.zip

Invoke-WebRequest "$Base/nltk_data.zip" -OutFile nltk_data.zip
Expand-Archive nltk_data.zip -DestinationPath .\venv -Force   # 解压到 venv 根目录（等价于 install.ps1 的 sys.prefix）
Remove-Item nltk_data.zip

Invoke-WebRequest "$Base/open_jtalk_dic_utf_8-1.11.tar.gz" -OutFile open_jtalk_dic.tar.gz
$pyopenjtalk_dir = python -c "import os, pyopenjtalk; print(os.path.dirname(pyopenjtalk.__file__))"
tar -xzf open_jtalk_dic.tar.gz -C $pyopenjtalk_dir
Remove-Item open_jtalk_dic.tar.gz
```

### A.6 验证

```powershell
python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

期望输出 `2.7.x+cu128 True NVIDIA GeForce RTX 5080`。

### A.7 之后的使用

与正文完全一致，只是「激活环境」从 `conda activate GPTSoVits` 换成 `.\venv\Scripts\Activate.ps1`（cmd 用 `venv\Scripts\activate.bat`）：

```powershell
cd G:\Projects\github\GPT-SoVITS
.\venv\Scripts\Activate.ps1
python tts_infer.py --role 星野 --text "欢迎来到我的博客！" --lang zh
```

### A.8 两条路线怎么选

| | conda 路线（正文） | venv 路线（本附录） |
|---|---|---|
| 安装 | 官方脚本一键完成 | 手动执行 A.1~A.5 五组命令 |
| 维护 | 官方脚本更新后可照着重跑 | 需自行对照脚本变化 |
| 运行结果 | 完全相同（同一套 pip 包、同一个 cu128 torch） | 同左 |

本机已有 Anaconda，直接走正文路线最省事；只有明确不想用 conda 时才建议走 venv 路线。

---

## 附录 B：本次安装踩坑实录（Windows 11 + RTX 5080 Laptop，2026-10-03）

> 从零安装到首次合成成功期间遇到的**全部问题**，按出现顺序记录现象、原因与完整解决方法。
> 快速排查表见第 9 节；这里是每个问题的完整过程（含原始报错特征与命令），换机器排错可按序参考。

### B.1 conda create 下载中断，随后 activate 提示环境不存在

**现象**

```
conda create -n GPTSoVits python=3.10 -y
……下载到一半：
('Connection broken: IncompleteRead(1418432 bytes read, 7892798 more expected)')
……
conda activate GPTSoVits
EnvironmentNameNotFound: Could not find conda environment: GPTSoVits
```

**原因**：直连 Anaconda 官方源（repo.anaconda.com）在国内网络不稳定，包下载被中途掐断，**环境创建根本没完成**（conda 失败后已自动清理残留目录），所以 activate 找不到它是必然结果，不是激活命令用错。

**解决**：配置清华镜像后重跑。`.condarc`（`C:\Users\Administrator\.condarc`）内容见 2.1 节；然后：

```cmd
conda create -n GPTSoVits python=3.10 -y
conda activate GPTSoVits
python --version        # 应输出 Python 3.10.22
```

**识别要点**：报错含 `Connection broken` / `IncompleteRead` → 网络原因；创建后 `conda info --envs` 里没有该环境 → 创建未完成，直接配镜像重跑即可。

### B.2 已有 Anaconda 却被建议安装 Miniconda（建议失误）

**现象**：安装指南最初让装 Miniconda，但机器上早已装有 Anaconda（`D:\Softwares\Coding\Anaconda`，conda 26.1.1）。

**原因**：`conda` 不在 PATH 中，仅凭 `conda` 命令找不到就误判"未安装"，没有检查自定义安装目录。

**解决**：无需安装 Miniconda（两者提供的是同一个 conda 工具），直接复用已有 Anaconda——用开始菜单的 **Anaconda Prompt**，或执行一次 `& "D:\Softwares\Coding\Anaconda\Scripts\conda.exe" init powershell` 后重开终端即可。

### B.3 装 ffmpeg 时报 gdk-pixbuf 链接错误（频道混装）

**现象**：`install.ps1` 第一步报错（脚本截断了细节，只显示一行）：

```
ERROR conda.core.link:_execute(1033): An error occurred while installing package 'conda-forge::gdk-pixbuf-2.42.12-hab781ea_1'.
```

手动重跑拿到完整日志后，真正的报错是：

```
librsvg: The post-link script did not complete.
g_module_open() failed for ...\libpixbufloader-svg.dll: '...': 找不到指定的程序。
```

**原因**：**频道混装导致的 ABI 冲突**。求解器把 Anaconda 官方源的 `libglib`/`pcre2`（`anaconda/pkgs/main`）与 conda-forge 的 `gdk-pixbuf`/`pango` 装进了同一个环境，conda-forge 的 gdk-pixbuf 加载图片解码器 DLL 时需要匹配的 glib 入口点，加载失败 → 安装后脚本失败 → 事务失败。（诊断依据：失败日志的包列表里同时出现 `anaconda/pkgs/main::libglib` 和 `conda-forge::gdk-pixbuf`。）

**解决**：启用严格频道优先级，保证同一环境只用一套生态：

```cmd
conda config --set channel_priority strict
```

（等价于在 `.condarc` 写 `channel_priority: strict`，已加入 2.1 节的模板。）之后 `conda install -n GPTSoVits -y -c conda-forge ffmpeg cmake` 一次通过，关键包全部来自 conda-forge。

**识别要点**：只要在 Windows 上用 `-c conda-forge` 装含 GUI 依赖链的包（ffmpeg 会拉 gdk-pixbuf/pango/glib），就必须有 `channel_priority: strict`，否则可能反复踩此坑。

### B.4 失败的事务把环境弄坏（conda-meta\history 丢失）

**现象**：B.3 失败之后，环境彻底"消失"：

```
conda activate GPTSoVits
EnvironmentNameNotFound: Could not find conda environment: GPTSoVits

conda install -n GPTSoVits ...
DirectoryNotACondaEnvironmentError: The target directory exists, but it is not a conda environment.
  target directory: C:\Users\Administrator\.conda\envs\GPTSoVits
```

**原因**：本机 conda 26.1.1 的实测行为——**失败的链接事务回滚时会删除环境的 `conda-meta\history` 文件**。conda 靠该文件识别环境，历史丢失后环境即"无效"（表现为 `conda info --envs` 不再列出它、activate/install 均报错）。

**识别方法**：对比正常环境，`conda-meta` 目录应包含"每个包一个 json + `created_at` + `history`"（本机正常 22 项）；损坏时恰好少 `history`（21 项）：

```cmd
dir "C:\Users\Administrator\.conda\envs\GPTSoVits\conda-meta" | find "history"
```

**解决**：环境内还没有有价值内容时，删除目录重建最简单：

```cmd
rmdir /s /q "C:\Users\Administrator\.conda\envs\GPTSoVits"
conda create -n GPTSoVits python=3.10 -y
```

**注意**：如果重建时环境里已有大量 pip 包/成果，请先确认无重要内容再删；重建后 pip 侧的东西（如 torchcodec）需要重新安装。

### B.5 torchcodec 在 PyTorch 官方索引没有 Windows 版（install.ps1 在 Windows 的必失败项）

**现象**：`install.ps1` 装 PyTorch 时报：

```
ERROR: Could not find a version that satisfies the requirement torchcodec (from versions: none)
```

**原因**：`install.ps1` 执行 `pip install torch torchcodec --index-url https://download.pytorch.org/whl/cu128`，而该索引里的 torchcodec **只有 Linux（manylinux）轮子，没有 Windows 轮子**，所以这行在 Windows 上必然失败（上游脚本的兼容问题，不是本机环境问题）。

**为什么不能直接跳过 torchcodec**：合成时需要读取参考音频，走的是 `GPT_SoVITS/TTS_infer_pack/TTS.py` 里 `_get_ref_spec() → torchaudio.load()`，torchcodec 是 torchaudio 的解码后端，缺了会在合成时报错。

**解决**：从 PyPI 单独预装**与 torch 版本配套**的 torchcodec（PyPI 有 Windows 轮子），再重跑 install.ps1——此时 torchcodec 已满足会被跳过，torch 仍从官方索引正常安装。

版本对照（torchcodec 官方兼容表：<https://github.com/pytorch/torchcodec>）：

| torchcodec | 适用 torch |
|---|---|
| 0.12 ~ 0.15 | ≥ 2.11 |
| 0.8 ~ 0.9 | 2.9 |
| 0.7 | 2.8 |

本机的配套与命令（先看 torch 版本再决定装哪个版本的 torchcodec）：

```cmd
pip show torch                  # 本机为 2.11.0+cu128
pip install torchcodec==0.15.0 -i https://pypi.tuna.tsinghua.edu.cn/simple
```

> 过程备注：最初按 torch 2.9 判断装了 torchcodec 0.9.1（读取 PyTorch 索引列表时排序方式有误，漏看了 2.10/2.11 的轮子）；装完 requirements 核对 torchaudio 版本（2.11.0）时发现并升级到 0.15.0。**判断版本请用 `sort -V` 或 `pip index versions`，不要用普通字典序。**

### B.6 opencc / pyopenjtalk 源码编译失败（cmake 太旧，不认识 VS 2026）

**现象**：`install.ps1` 执行 `pip install -r requirements.txt` 时报：

```
error: subprocess-exited-with-error
```

（脚本截断了细节；这是构建阶段的错误，不是下载错误。）

**原因**：`requirements.txt` 里 `opencc` 被强制源码安装（`--no-binary=opencc`）、`pyopenjtalk` 没有 Windows 轮子，两者都需要 **cmake + MSVC** 编译。而随 ffmpeg 一起装的 **conda 版 cmake 3.31.1 太旧，不认识本机的 VS Build Tools 2026**（它的生成器列表只到 "Visual Studio 17 2022"）。

**定位方法**：

```cmd
cmake --version                          # 3.31.1
cmake --help | findstr /i "visual studio"   # 只列出到 Visual Studio 17 2022，没有 2026
pip install opencc --no-binary=opencc --no-deps   # 单独复现，可看到完整构建报错
```

**解决**：升级 conda 环境的 cmake 到 4.4+（支持 VS 2026），然后重跑安装脚本：

```cmd
conda install -n GPTSoVits -y -c conda-forge "cmake>=4.4"
cmake --version                          # 应显示 4.4.3
pip install -r requirements.txt          # 重跑，opencc / pyopenjtalk / jieba_fast 均可编译通过
```

> 佐证：本项目在 Windows 上只有 3 个需要源码编译的包——`opencc`、`pyopenjtalk`、`jieba_fast`；用 cmake 4.x 编译全部成功。

### B.7 运行 tts_infer.py 报 ModuleNotFoundError: No module named 'AR'

**现象**：首次运行合成命令时报：

```
File "GPT_SoVITS/TTS_infer_pack/TTS.py", line 24, in <module>
    from AR.models.t2s_lightning_module import Text2SemanticLightningModule
ModuleNotFoundError: No module named 'AR'
```

**原因**：`AR`、`BigVGAN`、`feature_extractor` 等模块位于 `GPT_SoVITS\` 子目录中，导入链需要把**仓库根目录**和 **`GPT_SoVITS` 目录**都加进 `sys.path`（官方 `api_v2.py` 就是两个都加），脚本初版只加了前者。

**解决**：已在 `tts_infer.py` 的 `_get_pipeline()` 中修复（两个路径都会追加），直接重跑即可。

### B.8 PyCharm 提示未配置 Python 解释器

**现象**：PyCharm 打开项目后提示 "No Python interpreter configured"。

**原因**：本机的 conda 未加入 PATH，PyCharm 未能自动发现 conda 环境。

**解决**：File → Settings → Project: GPT-SoVITS → Python Interpreter → Add Interpreter：
- **System Interpreter** → 选择 `C:\Users\Administrator\.conda\envs\GPTSoVits\python.exe`；或
- **Conda Environment → Use existing** → Conda executable 填 `D:\Softwares\Coding\Anaconda\Scripts\conda.exe` → 环境下拉选 `GPTSoVits`。

配置后 PyCharm 的 Terminal 里执行 `python -c "import torch; print(torch.cuda.is_available())"` 应输出 `True`。

### B.9 最终可用状态（验证证据）

| 项目 | 状态 |
|---|---|
| conda 26.1.1（清华镜像 + `channel_priority: strict`） | ✓ |
| GPTSoVits 环境（`C:\Users\Administrator\.conda\envs\GPTSoVits`，Python 3.10.22） | ✓ |
| torch 2.11.0+cu128 / `torch.cuda.is_available()` | True，识别为 NVIDIA GeForce RTX 5080 Laptop GPU |
| torchaudio 2.11.0 / torchcodec 0.15.0（`torchaudio.load` 读参考音频） | ✓ |
| ffmpeg 7.1 / cmake 4.4.3 | ✓ |
| 首次合成（星野，中文） | ✓ `outputs\星野_20261003_161903_520.wav`（1.54s / 32kHz） |
| v2ProPlus 路径合成（爱丽丝，中文） | ✓ `outputs\爱丽丝_20261003_165001_115.wav` |
