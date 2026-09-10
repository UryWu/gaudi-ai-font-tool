# 输出目录（output_dir）详解

> 本文档从 `说明文档.md` 拆分而来，聚焦训练页与生成页的「输出目录」概念，方便查阅与外部分享。

前端两个页面都要求填写「输出目录」，但**含义和产出物完全不同**。混淆会导致模型找不到、或生字图片被放到错误位置。

## 训练页 `/train` 的 output_dir

**含义：你这次训练任务的「专属工作目录」**（既存训练数据，也存最终模型）。

自动产出物：

| 文件 / 目录 | 说明 |
|------------|------|
| `001_font/` | 从学习字库（ref_font）提取的字形图片，作为训练样本 |
| `test.npz` | 测试样本包（用于生成预览） |
| `checkpoint-last.pth` | **训练产出的 LoRA 字迹模型**（生成页要加载它） |
| `checkpoint-best.pth` | 验证集最优的中间模型 |
| `logs/` | 训练日志（位于 output_dir 的同级目录） |

**关键点：**
- `checkpoint-last.pth` 是后续生成页要用的模型，**必须记住这个目录**
- 训练完成后，前端会自动填入 `<output_dir>/checkpoint-last.pth`
- 断点续训：**不是**「同目录自动续训」，而是通过 `config.jsonc` 的 `resumeFrom` 显式指定
  checkpoint 触发（详见 [scripts-guide.md](scripts-guide.md) 第 6 节）；`continueEpochs` 控制追加轮数

## 生成页 `/generate` 的 output_dir

**含义：生字图片的「存放根目录」**（不是模型目录，是字形图片的归宿）。

按 Tab 不同，实际写入路径也不同：

| Tab | 模式 | 实际写入路径 |
|-----|------|-------------|
| 0 | 文本粘贴 | `<output_dir>/gen_YYYYMMDD_HHMMSS/` |
| 1 | TTF + 文本 | `<output_dir>/gen_YYYYMMDD_HHMMSS/` |
| 2 | TTF + 字符集 | `<output_dir>/group_01/`、`group_02/` ... |
| 3 | 失败重试 | `<output_dir>/gen_YYYYMMDD_HHMMSS/` |

**特点：**
- Tab 0/1/3：每次自动加时间戳子目录，不覆盖历史
- Tab 2：每个差集分组一个子目录，便于分批管理
- 文件名格式：`uni4E00_一.png`，可直接导入 FontLab / FontForge

## 训练页 → 生成页 的衔接流程

```
[训练页]                                                  [生成页]
output_dir = D:/fonts-work/train_v6/   →   AI模型 = D:/fonts-work/train_v6/checkpoint-last.pth
                                              output_dir = D:/fonts-work/generate_runs/
```

1. 训练完成后，记下训练页的 output_dir（checkpoint 在那里）
2. 进入生成页，**「AI 模型」填写**：`<训练页 output_dir>\checkpoint-last.pth`
3. **「输出目录」**填一个独立的图片存放位置（可以与训练页不同）

## 常见误区

| 错误做法 | 后果 |
|---------|------|
| 把模型目录当生成图片目录 | 训练数据被生成图片淹没 |
| 训练页 output_dir 指向 `model/` 预训练模型目录 | 训练数据混入预训练模型文件，难以管理 |
| 每次训练都换 output_dir | 旧 checkpoint 找不到，无法续训 |

## 推荐目录结构

```
D:/fonts-work/
├── train_v6/                  ← 训练页 output_dir
│   ├── 001_font/
│   ├── test.npz
│   └── checkpoint-last.pth
└── generate_runs/             ← 生成页 output_dir（图片存放根目录）
    ├── gen_20260417_143000/   ← Tab 0/1/3 自动生成
    └── GB2312_diff/           ← Tab 2 用户自定义
        ├── group_01/
        └── group_02/
```

**训练页 output_dir 与生成页 output_dir 应该分开**，便于管理与备份。