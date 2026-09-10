# 训练页使用指南 (http://localhost:7550/)

> 第一次打开训练页时的填表说明。配合 [data-pipeline.md](data-pipeline.md) · [api-training.md](api-training.md) · [how-engine-uses-fonts.md](how-engine-uses-fonts.md)

## ⚠️ 显存经验（GTX 1060 6GB）

| 配置 | 状态 |
|------|------|
| batch_size=64, LoRA r=32, num_fonts=1000 | ❌ CUDA OOM 段错误（退出码 0xC0000005）|
| batch_size=8, LoRA r=32, num_fonts=1000 | ❌ 显存仍爆（持续增长）|
| **batch_size=4, LoRA r=32, num_fonts=1000** | ✅ **OK**（max mem ~1.9GB）|
| batch_size=2 | 极保守，6GB 卡安全 |

> 冒烟用 batch_size=4 跑过 5 chars / 1 epoch（16s, loss=0.0293 正常）。**GTX 1060 6GB 用户必须用 batch≤4**。

## 页面结构

页面分两块：

```
┌────────────────────────────────────────────┐
│  路径配置 (Path Configuration)              │
│   - 基础模型                                │
│   - 源字体                                  │
│   - 学习字库TTF                             │
│   - 字形素材目录（images_dir 模式）         │
│   - 输出目录                                │
├────────────────────────────────────────────┤
│  训练参数 (Training Parameters)              │
│   - Epochs / Batch Size / LoRA r / alpha   │
│   - CFG / num_fonts / num_chars / etc.     │
└────────────────────────────────────────────┘
```

## 路径配置（4 个 input + 1 浏览按钮）

| 字段 | 默认值 | images_dir 模式填什么 |
|------|--------|------------------|
| **基础模型** | `G:\...\model\zi2zi-JiT-B-16.pth` | ✅ 留默认（预训练权重 2.15GB）|
| **源字体** | `G:\...\font\default.ttf` | ✅ 留默认（source 通道）|
| **学习字库TTF** | （空）| ⛔ **留空**（images_dir 模式不用）|
| **字形素材目录**（images_dir）| （空）| ✅ **必填**：`G:\Projects\projects_ai\gaudi-font-preprocess\data\sessions\<hash>\exported\<ts>` |
| **输出目录** | `G:\...\model\run` | ✅ 留默认（自动建 `train_images_{ts}/`）|

> 💡 **images_dir 自动识别**：填了「字形素材目录」后，前端 JS 自动调 `/api/train/prepare` 走 images_dir 模式；后端从 `<ts>/` 找 PNG（命名 `uniXXXX[_NN].png`）+ `fontlab_<ts>.csv` + `fontlab_<ts>.source_map.json` 三件套。

## 训练参数（关键值）

| 字段 | UI 默认值 | 推荐值 | 必须改？ |
|------|----------|--------|---------|
| **Epochs** | 200 | **1**（冒烟）/ **50**（正式训）| ✅ 必须改 |
| **Batch Size** | 64 | **4**（318 字小数据集）/ **8**（<100 字）| ✅ 必须改（太大 → `ZeroDivisionError`，64 在 6GB 显存会触发 CUDA OOM 段错误）|
| **LoRA r** | 32 | 32 | 留默认 |
| **LoRA alpha** | 32 | 32 | 留默认 |
| **CFG** | 2.6 | 2.6 | 留默认 |
| **num_fonts** | 1000 | **1000** | ✅ 必填 1000+（< 1000 → checkpoint shape mismatch）|
| **num_chars** | 200000 | 200000 | 留默认（兜底）|
| **max_chars_per_font** | 10000 | 10000 | 留默认 |
| **num_workers** | 0 | 0 | 留默认（单 GPU）|

### 为什么 num_fonts 必须 ≥ 1000

预训练权重 `model/zi2zi-JiT-B-16.pth` 是用 1000 个字体训练的，`font_embedding` 矩阵 shape 是 `[1001, 768]`（1000 类 + 1 pad）。如果训练时 `num_fonts=1`，模型会建 `[2, 768]`，`strict=True` 加载权重会报错：

```
RuntimeError: size mismatch for net.y_embedder.font_embedding.weight:
  copying a param with shape torch.Size([1001, 768]) from checkpoint,
  the shape in current model is torch.Size([2, 768]).
```

## 训练参数下方「取字数量」选项

UI 上有「800 字 / 3000 字 / 全部 / 手动输入」单选按钮：

- **冒烟**：选「手动输入」填 `5` 或 `10`
- **正式训**：选「全部」（或留空 = 不限）

## 操作步骤

### 步骤 1: 准备数据
1. 填好「字形素材目录」
2. 选好「取字数量」
3. 点左侧「**准备数据**」按钮
4. 看到 toast `数据准备完成: 318 个字符`
5. 「输出目录」input 自动更新为新建的 `train_images_{时间戳}/`

### 步骤 2: 启动训练
1. 检查训练参数（Epochs、Batch Size、num_fonts）
2. 点左侧「**开始训练**」按钮
3. 右上角状态指示灯变「训练中」（橙色）
4. 右侧日志终端开始滚动

### 步骤 3: 实时监控
- **状态指示灯**：训练中 → 已完成
- **Epoch 进度**：顶部统计面板
- **Loss / LR**：每 100 步打印一次
- **GPU 显存**：底部日志显示 `max mem: XXXXMB`

## 实时日志位置

| 日志类型 | 路径 | 怎么开 |
|---------|------|--------|
| Web UI 日志终端 | 训练页右侧黑底 | 不用动，自动滚 |
| 引擎训练日志 | `<批次>\.logs\train_<时间戳>.log` | `Get-Content -Wait` 或在文件管理器双击 |
| PS1 脚本日志 | `model\run\logs\ps1_<ts>.log` | 同上 |

## 训练完成产物

```
G:\Projects\projects_ai\gaudi-ai-font-tool\model\run\train_images_<时间戳>\
├── 001_font/                  # 拼好的 1024×256 复合图
├── test.npz
├── checkpoint-last.pth        # ← 要给「字库生字」页用的
└── checkpoint-best.pth        # 验证集最优
```

## 怎么用训练好的模型

1. 复制 `checkpoint-last.pth` 的绝对路径
2. 打开 http://localhost:7550/generate
3. 在「AI模型」输入框粘贴路径
4. 选「字库生字」Tab（如「TTF + 字符集」）
5. 选 TTF + 字符集差集（你的源 TTF 里**缺失**的字）→ AI 用你的书法风格生字

## 故障排查

| 症状 | 排查 |
|------|------|
| `size mismatch for font_embedding` | num_fonts < 1000，改 ≥ 1000 |
| `ZeroDivisionError: float division by zero` | 数据集太小或 batch_size 太大，调小 batch |
| `CUDA out of memory` | batch_size 调小（如 4 → 2）|
| `ModuleNotFoundError: No module named 'xxx'` | `uv pip install --python .venv/Scripts/python.exe xxx` |
| 训练秒退 | 看 `<批次>\.logs\train_<时间戳>.log` 完整堆栈 |
| `char_count: 0` | images_dir 路径错，检查后端能访问 |

## 端到端冒烟 checklist

- [ ] 训练页打开正常（http://localhost:7550/）
- [ ] 5 个路径 input 都填好
- [ ] `num_fonts=1000, epochs=1, batch_size=4`
- [ ] 字形素材目录 = 预处理端原子化导出的 PNG 子目录
- [ ] 点「准备数据」→ 看到 `数据准备完成: N 个字符`
- [ ] 点「开始训练」→ 状态变「训练中」
- [ ] 右侧日志显示 `Epoch: [0] ... loss: X.XXXX` 即正常
- [ ] 几秒到几分钟后 `status=completed`，`checkpoint-last.pth` 在 `train_images_<ts>/` 下
