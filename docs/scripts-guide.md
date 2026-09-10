# Scripts 使用指南

> `scripts/` 目录与项目根的 `.ps1` / `.bat` 脚本完整说明。所有脚本都从项目根运行。

## 目录速查

| 入口 | 脚本 | 启动方式 | 配置文件 |
|------|------|---------|---------|
| **Flask 启动** | `start-ai-font-port-7550.ps1` / `.bat` | 双击 / `powershell -File ...` | `config.py` |
| **Flask 停止** | `stop-ai-font-port-7550.ps1` / `.bat` | 同上 | — |
| **训练（独立）** | `scripts/train_lora.ps1` → `train_lora.py` | `powershell -ExecutionPolicy Bypass -File scripts\train_lora.ps1` | `config.jsonc` |
| **生成字（独立）** | `scripts/gen_chars.ps1` → `gen_chars.py` | 同上 | `gen_chars.py` 顶部 CONFIG 区 |
| **训练（API）** | `scripts/train-via-api.ps1` | 同上 | ps1 顶部变量 |
| **生成字（API）** | （在 Flask UI 触发） | http://localhost:7550/generate | — |

> **独立脚本 vs API 脚本**：独立脚本直接调引擎/Python 模块，**无需启 Flask**。API 脚本走 Flask REST 接口，需要后端在跑。

---

## 1. `start-ai-font-port-7550.ps1` / `.bat`

启动 Flask 后端服务（开发模式），监听 `http://localhost:7550`。

```bash
# PowerShell
powershell -ExecutionPolicy Bypass -File start-ai-font-port-7550.ps1

# 或双击 .bat
start-ai-font-port-7550.bat
```

**配置：** `config.py`（路径/端口）+ `config.jsonc`（训练参数持久化）

**停止：** `stop-ai-font-port-7550.ps1` 或 `.bat`（杀整棵 7550 进程树 + 残留 app.py）

---

## 2. `scripts/train_lora.ps1` — **推荐训练入口**

从 `config.jsonc` 读所有配置（路径 + 训练超参），调 `utils/train_manager` 完成 prepare → train → 轮询，无需 Flask。

```bash
powershell -ExecutionPolicy Bypass -File scripts\train_lora.ps1
```

**工作流：**

1. 编辑项目根 `config.jsonc`（已 gitignore，本地值）：
   - `baseCheckpoint`：预训练权重路径（默认指向 `model/zi2zi-JiT-B-16.pth`）
   - `imagesDir`：字形素材目录（images_dir 模式必填）
   - `sourceFont`：源字体 TTF
   - `outputDir`：训练产物根目录
   - `epochs` / `batchSize` / `loraR` / `loraAlpha` / `cfg` / `numFonts` / `numChars` / `maxCharsPerFont` / `numWorkers`
   - `charCountMode`：`"all"`=全部（推荐） / `"custom"`=用 `charCountCustom` / `"800"`/`"3000"`=前 N 字
2. 跑脚本
3. 输出目录结构：
   ```
   <outputDir>/train_images_<时间戳>/
   ├── 001_font/*.png              # 1024×256 复合训练图
   ├── test.npz                     # 门禁文件
   ├── checkpoint-last.pth          # 训练完模型（生字页用这个）
   ├── .logs/                       # ★所有训练日志统一在这里（带时间戳）
   │   ├── engine_<时间戳>.log      # 引擎原始输出
   │   └── summary_<时间戳>.log     # 训练脚本汇总（路径/参数/进度/用时）
   └── gen_<时间戳>/                # 生字产物（用该 checkpoint 生成时自动落这里）
       ├── gen_char/                # ★字形 PNG
       │   └── uniXXXX_字.png
       └── .logs/
           └── gen_summary_<时间戳>.log
   ```
4. 日志规则：**所有日志都在批次目录 `.logs/` 内，文件名带时间戳**，多次训练/续训互不覆盖，不再有 `<outputDir>/.logs/` 这样的根级散落日志。

5. **Checkpoint 自动保存 + 断点续训：**
   - **每轮都存**：`config.jsonc` 的 `saveLastFreq` 字段（默认 1）控制每 N 轮存一次 `checkpoint-last.pth`。
     - `saveLastFreq=1`（推荐）：每轮存，10 epoch = 10 个 ckpt（每个 ~12MB LoRA），中断最多丢 1 epoch
     - `saveLastFreq=5`（引擎默认）：10 epoch 只存 2 个 ckpt（epoch=5 和 epoch=10），中间崩了从 5 续
   - **`checkpoint-best.pth` 关闭**（`save_best_freq=0`），不存冗余备份
   - **断点续训机制**（`utils/train_manager.start_training` 自动检测）：
     1. 重跑 `train_lora.ps1` 选**同一 outputDir**（脚本会落到同一 `train_images_<ts>/` 批次）
     2. 引擎发现 `<outputDir>/train_images_<ts>/checkpoint-last.pth` 存在 → 自动加 `--resume` 参数
     3. 读 ckpt 的 `epoch` 字段 → `total_epochs` 自动调为 `max(你设的, start_epoch + 1)`
     4. 引擎从 `epoch+1` 继续训
   - **显式续训示例**（如想跑 50 epoch 实际只跑了 20）：
     1. 跑一次 `train_lora.ps1`（`epochs=50`），训练到 epoch=20 时 Ctrl+C
     2. 修改 `config.jsonc`：`epochs=80`（或直接保留 50 让引擎从 20 → 50）
     3. 再跑 `train_lora.ps1` → 自动从 epoch=20 续训
   - **任何中断**（Ctrl+C / 关窗口 / 杀进程）→ 已有 `checkpoint-last.pth`（最新一轮权重）→ 下次跑自动 `--resume`

**关键经验（GTX 1060 6GB）：**
- `batchSize ≤ 4`（batch=64 触发 CUDA OOM 段错误退出码 0xC0000005）
- `numFonts ≥ 1000`（与预训练权重 shape 匹配，否则报 `size mismatch`）

---

## 3. `scripts/gen_chars.ps1` — **推荐生字入口**

从 `gen_chars.py` 顶部 CONFIG 区读配置，直接 subprocess 调 `zi2zi-JiT/generate_chars.py`，无需 Flask。

```bash
powershell -ExecutionPolicy Bypass -File scripts\gen_chars.ps1
```

**配置：** 编辑 `scripts/gen_chars.py` 顶部 CONFIG 区：
- `CHECKPOINT`：训练产出的 `checkpoint-last.pth` 路径（★输出位置由它决定）
- `REF_FONT`：基本字库 TTF（**填你的个人字库**，用于 ref 网格风格参考）
- `SOURCE_FONT`：源字体 TTF（**必须字形齐全**，推荐 `C:\Windows\Fonts\simfang.ttf` 仿宋）
- `INPUT_TEXT`：要生成的文本
- `INPUT_TEXT_FILE` / `INPUT_TEXT_STDIN`：替代 `INPUT_TEXT`
- `MULTIPLIER`：每字生成张数（批量生字建议 1）
- `CFG` / `BATCH_SIZE`

> ⚠️ `SOURCE_FONT` 不能用 `default.ttf`（cmap 虚报，常用字渲染成空白被跳过）；也不能用 `simsunb.ttf`（扩展区专用，BMP 常用字不在内）。用 `simfang.ttf`（仿宋，2.85 万字，字形真实）最稳。

**输出（自动落在 CHECKPOINT 所在批次目录下）：**
```
<CHECKPOINT所在批次>/gen_<时间戳>/
├── gen_char/                    # ★字形图
│   ├── uni4F60_你.png           # FontLab 命名，直接导入字体编辑器
│   └── uni0030_0.png
└── .logs/
    └── gen_summary_<时间戳>.log  # 生成日志：路径/参数/引擎用时/总用时
```

**哪个模型生成，产物就落在哪个批次目录下**——无需配置输出路径。

---

## 4. `scripts/train-via-api.ps1` — 旧版训练脚本

**仍在工作，但已被 `train_lora.ps1` 替代**。保留理由：保留 PS1 硬编码变量形态，方便习惯这种工作流的用户。

需要修改训练参数**直接编辑脚本顶部变量**（行号）：
```powershell
21: $CHAR_COUNT = $null       # 学习字数（$null=全部）
22: $EPOCHS = 1
25: $BATCH_SIZE = 4
29: $NUM_FONTS = 1000         # 不要改，必须 ≥1000
```

---

## 5. `scripts/gen_chars.py` 配置文件（CONFIG 区）

文件顶部常量（**直接编辑后重启脚本即生效**）：

```python
# —— 模型位置 ——
CHECKPOINT = r"...\train_images_<ts>\checkpoint-last.pth"

# —— 基本字库 / 源字体 ——
REF_FONT = r"...\font\default.ttf"
SOURCE_FONT = r"...\font\default.ttf"

# —— 输入文本（三选一）——
INPUT_TEXT = "你好，世界！"
INPUT_TEXT_FILE = ""        # 留空 = 不读文件
INPUT_TEXT_STDIN = False    # True 时从 stdin 读

# —— 输出位置 ——
OUTPUT_DIR = r"...\model\run"   # 脚本会自动建 gen_<ts>/ 子目录

# —— 生成参数 ——
MULTIPLIER = 5
CFG = 4.0
BATCH_SIZE = 4
```

---

## 6. `stop-ai-font-port-7550.ps1` / `.bat`

杀占用 7550 端口的所有 Flask 进程（含整个进程树，避免孤儿）+ 兜底清理残留 app.py python 进程。

```bash
powershell -ExecutionPolicy Bypass -File stop-ai-font-port-7550.ps1
```

---

## 完整工作流（推荐顺序）

```bash
# 1. 启动后端（可选，仅当用 UI/API 时）
powershell -ExecutionPolicy Bypass -File start-ai-font-port-7550.ps1
# 浏览器开 http://localhost:7550

# 2. 训练（脚本模式，无需后端）
#    编辑 config.jsonc（paths + 超参）→ 跑：
powershell -ExecutionPolicy Bypass -File scripts\train_lora.ps1

# 3. 生成字（脚本模式，无需后端）
#    编辑 scripts\gen_chars.py CONFIG 区（CHECKPOINT + INPUT_TEXT）→ 跑：
powershell -ExecutionPolicy Bypass -File scripts\gen_chars.ps1

# 4. 停止后端（用完后）
powershell -ExecutionPolicy Bypass -File stop-ai-font-port-7550.ps1
```

---

## 目录布局（统一约定）

```
model/run/                                       # 训练根目录（config.jsonc 的 outputDir）
├── train_images_<ts1>/                           # 训练批次 A（一次训练 = 一个批次）
│   ├── 001_font/*.png                            # 复合训练图
│   ├── test.npz
│   ├── checkpoint-last.pth                       # 本次训练的模型
│   ├── .logs/                                    # ★该批次所有日志
│   │   ├── engine_<时间戳>.log                   #   引擎原始日志
│   │   └── summary_<时间戳>.log                  #   训练脚本汇总
│   └── gen_<时间戳>/                             # ★该模型生成的产物（嵌套在批次下）
│       ├── gen_char/                             #   字形 PNG
│       │   ├── uni4F60_你.png
│       │   └── uni0030_0.png
│       └── .logs/
│           └── gen_summary_<时间戳>.log          #   生成日志
│
└── train_images_<ts2>/                           # 训练批次 B（再训一次 = 新批次，与 A 并列）
    ├── .logs/
    │   ├── engine_<时间戳>.log
    │   └── summary_<时间戳>.log
    ├── checkpoint-last.pth
    └── gen_<时间戳>/
        ├── gen_char/
        └── .logs/
```

**核心规则：**
1. **训练批次并列**在 `model/run/` 下，每批次一个 `train_images_<ts>/`
2. **日志全在批次内** `<批次>/.logs/`，文件名带时间戳（`engine_*` = 引擎原始，`summary_*` = 脚本汇总）
3. **生字产物紧跟模型**：用哪个 checkpoint 生成，`gen_<ts>/` 就落在哪个批次目录下
4. **字形图统一放 `gen_char/`**，日志统一放 `.logs/`
5. `model/run/.logs/` 这类根级散落日志**不再产生**
