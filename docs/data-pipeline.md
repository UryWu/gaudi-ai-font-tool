# 数据流水线：预处理工具 → AI 训练工具

> 两个项目通过「字形训练包」对接的全流程说明。
> 配套文档：[how-engine-uses-fonts.md](how-engine-uses-fonts.md) · [api-training.md](api-training.md) · [make-personal-font.md](make-personal-font.md)

## 端到端全景

```
┌─────────────────────────────────────────┐         ┌──────────────────────────────────────┐
│  gaudi-font-preprocess  (port 7500)     │         │  gaudi-ai-font-tool  (port 7550)    │
│  Flask + 原图处理 + OCR 标注            │         │  Flask + zi2zi-JiT 训练 + AI 生字    │
└─────────────────────────────────────────┘         └──────────────────────────────────────┘
       │                                                       │
       │ ① 拍照 → 切割 → 缩放 → 标注                            │ ④ assemble 复合图 → 训练
       │ ② 「导出训练包」按钮：                                 │ ⑤ 产出 checkpoint-last.pth
       │    PNG (460字符+26px padding, 512画布) +                │ ⑥ 训练页 / 生成页用 checkpoint
       │    CSV (filename/unicode/char) +                       │
       │    source_map.json                                    │
       ▼                                                       ▼
       exported/<ts>/                                          model/run/train_images_<ts>/
       ├── uni4E00.png                                         ├── 001_font/00000_入.png
       ├── uni4E00_01.png                                       │   (1024×256 复合图)
       ├── ...                                                 ├── test.npz
       ├── fontlab_<ts>.csv                                    ├── checkpoint-last.pth
       └── fontlab_<ts>.source_map.json                        └── .logs/train_<ts>.log
                       │                                                
                       │ ③ 路径复制到训练页「字形素材目录」                      
                       └─────────────────────────────────────→                    
```

## 两端契约

### 预处理端产出（每 session 多次导出，按 mtime 倒序）

每个 `<session>/exported/<ts>/` 是「原子化训练包」：

| 文件 | 必需 | 说明 |
|------|------|------|
| `*.png` | ✅ | N 张，命名 `uniXXXX[_NN].png`（uniXXXX = Unicode 大写十六进制）|
| `fontlab_<ts>.csv` | ✅ | 列：`filename,unicode,character,simplified,traditional` |
| `fontlab_<ts>.source_map.json` | ✅ | `{scaled_NNNN.png: uniXXXX.png}` 映射 |

PNG 尺寸：**512×512 画布 + 460 字符 + 26px padding**（fill_ratio=0.9），与 train_manager 渲染逻辑对齐。

**重复字符支持：** 同字可有多张样本（统计学习更稳），用 `uniXXXX_01.png`、`uniXXXX_02.png` 等后缀区分，CSV 同步重复。

### 接口（预处理 → 训练）

| 端点 | 方法 | 用途 |
|------|------|------|
| `/api/list_sessions` | GET | 列所有 session；每 session 含 `exports[]` 字段 |

**`exports[]` 字段（新增）：**

```json
{
  "ts": "20260910_013320",
  "path": "G:\\...\\exported\\20260910_013320",
  "png_count": 318,
  "csv_rows": 318,
  "created_at": "2026-09-10T01:33:23"
}
```

数据来源 = 磁盘扫描（不维护数据库），按 mtime 倒序，半成品也列出。

### 训练端消费

ai-font-tool 侧通过 `utils/import_images.py` 自动识别路径：

**解析优先级**（`import_images._scan_images_dir`）：

1. `<images_dir>/source_map.json`
2. `<images_dir>/../source_map.json`
3. `<images_dir>/../exported/source_map.json`
4. `<images_dir>/../exported/*.source_map.json` ← 通配符兼容时间戳命名
5. **fallback: PNG 命名 `uniXXXX.png`** ← 主流路径，不依赖 source_map
6. fallback: `uniXXXX_字.png` 命名

走通任一路径即可训练，**最低要求是 PNG 用 `uniXXXX.png` 命名**。

## 完整 SOP（用户操作）

### Step 1: 在 gaudi-font-preprocess 里准备字形
1. 拍照上传（7500 端口 `/adjust` 等页面）
2. 切割 → 缩放 → 标注
3. 点击「**导出训练包**」按钮 → 自动在 `exported/<ts>/` 出三件套

### Step 2: 复制路径到 ai-font-tool
打开训练页（7550 端口），在「**字形素材目录**」输入框填：
```
G:\Projects\projects_ai\gaudi-font-preprocess\data\sessions\<hash>\exported\<ts>
```
或用 `scripts/train-via-api.ps1` 改顶部 `$IMAGES_DIR` 变量。

### Step 3: 训练参数
- 「源字体」= `font\default.ttf`（自动填）
- 「基础模型」= `model\zi2zi-JiT-B-16.pth`（自动填）
- 「学习字库TTF」= **留空**（走 images_dir 模式时不用）
- 「输出目录」= `model\run`（自动填）
- Epochs/Batch Size/LoRA r 等按需调

### Step 4: 准备数据 → 开始训练
- 点「准备数据」→ 后端拼 1024×256 复合图，~1-2 秒
- 点「开始训练」→ 引擎 subprocess 跑
- 状态轮询：`/api/train/status`

## 端到端冒烟 checklist

- [ ] torch CUDA 装好：`python -c "import torch; print(torch.cuda.is_available())"` → True
- [ ] 引擎 `G:\Projects\projects_ai\zi2zi-JiT\lora_finetune_jit.py` 存在
- [ ] `model\zi2zi-JiT-B-16.pth` 存在（2.15 GB）
- [ ] `font\default.ttf` 存在
- [ ] 预处理端有原子化导出目录（PNG + CSV + source_map 三件套）
- [ ] `scripts/train-via-api.ps1` 顶部 `$CHAR_COUNT=5, $EPOCHS=1` 跑通
- [ ] 看 `model\run\logs\training.log` 验证 loss/epoch 正常
- [ ] 完整训练：`$CHAR_COUNT=$null, $EPOCHS=50`

## 多 session / 多版本管理

- **多 session 互不干扰**：`/api/list_sessions` 返回所有 session，各自 `exports[]` 独立
- **多版本共存**：每次「导出训练包」生成新时间戳子目录，旧版本不删（用户手动管理磁盘）
- **UI 选择策略（暂不实现）**：
  - 当前：用户从 `list_sessions` 复制 `path` 字段，填到训练页输入框
  - 未来：训练页加「最近导出」下拉（消费 list_sessions 数据）

## 故障排查

| 症状 | 排查 |
|------|------|
| `char_count=0` | images_dir 路径错？找的是子目录里的 PNG 还是父目录？查 `_scan_images_dir` 解析优先级 |
| `data_dir 不存在: ...` | output_dir 没建？检查 `model\run/` 可写 |
| 训练秒退，log 报 `FileNotFoundError` | base_checkpoint 路径错 / engine `lora_finetune_jit.py` 找不到 |
| `RuntimeError: CUDA out of memory` | batch_size 调小（如 4→2），num_workers 设为 0 |
| train loss 不下降 | LoRA r/epochs 调大；先确认 ref 字里有 8 个能渲 |
