# Scripts 使用指南

> `scripts/` 目录与项目根的 `.ps1` / `.bat` 脚本完整说明。所有脚本都从项目根运行。

## 目录速查

| 入口 | 脚本 | 启动方式 | 配置文件 |
|------|------|---------|---------|
| **Flask 启动** | `start-ai-font-port-7550.ps1` / `.bat` | 双击 / `powershell -File ...` | `config.py` |
| **Flask 停止** | `stop-ai-font-port-7550.ps1` / `.bat` | 同上 | — |
| **训练（独立）** | `scripts/train-lora.ps1` → `train_lora.py` | `powershell -ExecutionPolicy Bypass -File scripts\train-lora.ps1` | `config.jsonc` |
| **生成字（独立）** | `scripts/gen-chars.ps1` → `gen_chars.py` | 同上 | `gen_chars.py` 顶部 CONFIG 区 |
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

## 2. `scripts/train-lora.ps1` — **推荐训练入口**

从 `config.jsonc` 读所有配置（路径 + 训练超参），调 `utils/train_manager` 完成 prepare → train → 轮询，无需 Flask。

```bash
powershell -ExecutionPolicy Bypass -File scripts\train-lora.ps1
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
   ├── 001_font/*.png           # 1024×256 复合训练图
   ├── test.npz                  # 门禁文件
   ├── .logs/training.log         # 引擎实时日志
   ├── checkpoint-last.pth       # 训练完模型（生字页用这个）
   └── checkpoint-best.pth
   ```
4. 日志双层：
   - 批次内 `<batch>/.logs/training.log`（引擎）
   - 输出根 `<outputDir>/.logs/train_<时间戳>.log`（汇总：路径/参数/用时）

**关键经验（GTX 1060 6GB）：**
- `batchSize ≤ 4`（batch=64 触发 CUDA OOM 段错误退出码 0xC0000005）
- `numFonts ≥ 1000`（与预训练权重 shape 匹配，否则报 `size mismatch`）

---

## 3. `scripts/gen-chars.ps1` — **推荐生字入口**

从 `gen_chars.py` 顶部 CONFIG 区读配置，直接 subprocess 调 `zi2zi-JiT/generate_chars.py`，无需 Flask。

```bash
powershell -ExecutionPolicy Bypass -File scripts\gen-chars.ps1
```

**配置：** 编辑 `scripts/gen_chars.py` 顶部 CONFIG 区：
- `CHECKPOINT`：训练产出的 `checkpoint-last.pth` 路径
- `REF_FONT` / `SOURCE_FONT`：TTF 路径
- `INPUT_TEXT`：要生成的文本（支持整段、空白、段首缩进——但引擎不支持空格字符生成）
- `INPUT_TEXT_FILE` / `INPUT_TEXT_STDIN`：替代 `INPUT_TEXT`
- `OUTPUT_DIR`：落在该目录下 `gen_<时间戳>/` 子目录（默认 `model/run/`）
- `MULTIPLIER`：每字生成张数（多采样便于人工筛选）
- `CFG` / `BATCH_SIZE`

**输出：**
```
<OUTPUT_DIR>/gen_<时间戳>/
├── uniXXXX_字.png 或 uXXXXX_字.png  # FontLab 命名，直接导入字体编辑器
└── （无 .logs/ 下属，每个 .png 自带 unicode 信息）

<OUTPUT_DIR>/.logs/gen_<时间戳>.log  # 详细日志：路径/参数/引擎用时/总用时
```

---

## 4. `scripts/train-via-api.ps1` — 旧版训练脚本

**仍在工作，但已被 `train-lora.ps1` 替代**。保留理由：保留 PS1 硬编码变量形态，方便习惯这种工作流的用户。

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
powershell -ExecutionPolicy Bypass -File scripts\train-lora.ps1

# 3. 生成字（脚本模式，无需后端）
#    编辑 scripts\gen_chars.py CONFIG 区（CHECKPOINT + INPUT_TEXT）→ 跑：
powershell -ExecutionPolicy Bypass -File scripts\gen-chars.ps1

# 4. 停止后端（用完后）
powershell -ExecutionPolicy Bypass -File stop-ai-font-port-7550.ps1
```

---

## 目录布局（统一约定）

所有训练和生成产物并列在 `model/run/` 根下：

```
model/run/
├── train_images_<ts1>/    ← 训练批次 A（train-lora.ps1 或 UI 训练）
│   ├── 001_font/*.png
│   ├── .logs/training.log
│   └── checkpoint-last.pth
├── train_images_<ts2>/    ← 训练批次 B（修改 config.jsonc 后第二次训练）
│
├── gen_<ts1>/             ← 字形生成（gen-chars.ps1 跑的「你好世界」）
│   ├── uni4F60_好.png
│   └── uni4E16_世.png
└── gen_<ts2>/             ← 第二次生字（改了 INPUT_TEXT 再跑）
```

**前缀语义：** `train_images_<ts>` = 训练产物 / `gen_<ts>` = 生成产物。`<ts>` 是时间戳，天然按时间排序，方便翻历史。
