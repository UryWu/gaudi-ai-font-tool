# 训练个人字库：API + 脚本路径

> 当不想用 Web UI 时，可直接调 API 跑端到端训练。本文档说明 API 契约 + 配套 PowerShell 脚本。

## 路径对比

| 路径 | 适合场景 | 入口 |
|------|---------|------|
| **UI**（训练页 http://localhost:7550/）| 手动操作、可视化 | 浏览器 |
| **API**（本机 HTTP）| 脚本/集成测试/CI | curl / urllib / PowerShell |
| **脚本**（一键跑）| 端到端冒烟 | `scripts/train-via-api.ps1` |

## API 契约

Base: `http://localhost:7550`

### 1. `POST /api/train/prepare` — 准备训练数据

**images_dir 模式**（推荐，用外部 PNG）：

```json
{
  "images_dir": "G:\\...\\gaudi-font-preprocess\\data\\sessions\\<session>\\scaled",
  "source_font": "G:\\...\\gaudi-ai-font-tool\\font\\default.ttf",
  "output_dir": "G:\\...\\gaudi-ai-font-tool\\model\\run",
  "char_count": 319
}
```

`char_count` 可选；缺省 = 用全部。返回：
```json
{
  "success": true,
  "char_count": 319,
  "data_dir": "G:\\...\\model\\run\\train_images_20260910_003211",
  "test_npz": "G:\\...\\model\\run\\train_images_20260910_003211\\test.npz",
  "skipped": 0
}
```

**传统模式**（用 ref_font 渲染）：

```json
{
  "ref_font": "G:\\path\\to\\your-font.ttf",
  "source_font": "G:\\...\\font\\default.ttf",
  "output_dir": "G:\\...\\model\\run",
  "char_count": null
}
```

**`images_dir` 解析优先级**（见 `utils/import_images.py:_scan_images_dir`）：

1. `images_dir/source_map.json`（最优）
2. `images_dir/../source_map.json`
3. `images_dir/../exported/source_map.json`
4. `images_dir/../exported/*.source_map.json`（任何匹配）
5. fallback: `images_dir/uniXXXX.png` 命名
6. fallback: `images_dir/NNNNN_字.png` 命名

### 2. `POST /api/train/start` — 启动训练

用 Step 1 返回的 `data_dir` 调：

```json
{
  "output_dir": "<data_dir>",
  "data_path": "<data_dir>",
  "test_npz_path": "<data_dir>\\test.npz",
  "base_checkpoint": "G:\\...\\model\\zi2zi-JiT-B-16.pth",
  "source_font": "G:\\...\\font\\default.ttf",
  "epochs": 50,
  "batch_size": 8,
  "lora_r": 32,
  "lora_alpha": 32,
  "cfg": 2.6,
  "num_fonts": 1,
  "num_chars": 200000,
  "max_chars_per_font": 10000,
  "num_workers": 0
}
```

返回 `{"success": true, "message": "训练已启动"}` 后立即可查状态。

### 3. `GET /api/train/status` — 轮询状态

返回：
```json
{
  "status": "training",
  "current_epoch": 12,
  "total_epochs": 50,
  "current_loss": 0.087,
  "current_lr": 1e-4,
  "error_message": ""
}
```

`status` 状态机：`idle → preparing → training → completed | error`

### 4. `POST /api/train/stop` — 停止

随时打断，`status` 会回 `idle`。

## 配套脚本

### `scripts/train-via-api.ps1`

一键跑完整 prepare → start → poll 流程。PowerShell 5.1+ 即可（BOM 已加）。

**用法：**
```powershell
# 改脚本顶部的路径配置（IMAGES_DIR / SOURCE_FONT / OUTPUT_DIR / BASE_CHECKPOINT / CHAR_COUNT 等）
# 然后跑：
powershell -ExecutionPolicy Bypass -File scripts\train-via-api.ps1
```

**PS1 自身日志：** 脚本用 `Start-Transcript` / `Stop-Transcript` 把所有 print 输出**同步**写到：
```
G:\...\model\run\logs\ps1_<时间戳>.log
```
（不想要的话注释掉脚本头部的 `Start-Transcript` 那行）

**冒烟测试（5 个字 + 1 epoch）：**
```powershell
# 在脚本顶部把 $CHAR_COUNT = 5，$EPOCHS = 1
# 跑完后看 <批次>\.logs\engine_<时间戳>.log
```

**完整训练（319 字 + 50 epoch）：**
```powershell
# $CHAR_COUNT = $null（用全部）
# $EPOCHS = 50
# 预计 GTX 1060 6GB 上跑 4-8 小时
```

## UI 路径（新加的「字形素材目录」输入框）

训练页（http://localhost:7550/）现在多了一栏：

| 字段 | 填什么 |
|------|--------|
| 基础模型 | `G:\...\model\zi2zi-JiT-B-16.pth`（默认已填）|
| 源字体 | `G:\...\font\default.ttf`（默认已填）|
| 学习字库TTF | **不填**（走 images_dir 模式时不需要）|
| **字形素材目录** | `G:\...\gaudi-font-preprocess\data\sessions\<session>\scaled`（必填）|
| 输出目录 | `G:\...\model\run`（默认已填，会建 `train_images_{ts}/` 子目录）|

操作流程：填好「字形素材目录」→ 选「取字数量」→ 准备数据 → 开始训练。

## 关键产物位置

训练完成后：

```
model/run/train_images_<ts>/
├── 001_font/                  # 1024×256 复合图（引擎直接读）
│   ├── 00000_入.png
│   ├── 00001_牲.png
│   └── ...
├── test.npz                   # 门禁文件（训练不消费）
├── checkpoint-last.pth        # ← 你要的：续训/生成用这个
└── checkpoint-best.pth        # 验证集最优
```

日志在批次目录内 `<批次>/.logs/engine_<时间戳>.log`（点前缀目录，引擎扫描跳过，不会被当训练数据）。

## 端到端冒烟 checklist

- [ ] `python -c "import torch; torch.cuda.is_available()"` 返回 True
- [ ] 引擎 `G:\Projects\projects_ai\zi2zi-JiT\lora_finetune_jit.py` 存在
- [ ] `model/zi2zi-JiT-B-16.pth`（2.15GB）在
- [ ] `font/default.ttf` 在
- [ ] `IMAGES_DIR` 路径正确（个人 PNG 目录）
- [ ] 先用 `CHAR_COUNT=5, EPOCHS=1` 跑通完整流程（约 5 min）
- [ ] 再用 `CHAR_COUNT=319, EPOCHS=50` 跑完整训练
