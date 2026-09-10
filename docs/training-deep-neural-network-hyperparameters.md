# 训练内部机制（深度学习细节）

> 本文档梳理 zi2zi-JiT 引擎的**训练算法细节**：损失函数、优化器、学习率、LoRA、精度等。
> 源码位置：`G:\Projects\projects_ai\zi2zi-JiT\`（引擎仓库，不在本项目内）。
> 相关：`docs/engine-patch.md`（本地补丁）、`docs/scripts-guide.md`（怎么跑）。

## 0. 概览

| 维度 | 方案 |
|------|------|
| 模型 | **JiT-B/16**（ViT-Base，patch 16，256×256 输入） |
| 微调方式 | **LoRA**（低秩适配，只训少量参数） |
| 生成范式 | **Flow Matching / Rectified Flow**（速度场回归，v-prediction） |
| 任务 | 字体内风格迁移（source 标准字形 + ref 风格参考 → target 个人笔迹） |
| 采样 | Heun 采样器 + CFG（classifier-free guidance） |

---

## 1. 损失函数：Flow Matching（L2 / MSE）

`denoiser.py:63-81`

```python
def sample_t(self, n):                        # 时间步采样：logit-normal
    z = torch.randn(n) * self.P_std + self.P_mean
    return torch.sigmoid(z)                   # P_mean=-0.8, P_std=0.8

def forward(self, x, labels):
    labels_dropped = self.drop_labels(labels)
    t = self.sample_t(x.size(0)).view(-1, 1, 1, 1)
    e = torch.randn_like(x) * self.noise_scale          # 噪声 (noise_scale=1.0)

    z = t * x + (1 - t) * e                             # 线性插值：数据 ←→ 噪声
    v = (x - z) / (1 - t).clamp_min(self.t_eps)         # 目标速度 (t_eps=0.05)

    x_pred = self.net(z, t.flatten(), labels_dropped)   # 模型预测 x
    v_pred = (x_pred - z) / (1 - t).clamp_min(self.t_eps)   # 换算成速度

    loss = (v - v_pred) ** 2                            # L2 loss
    return loss.mean(dim=(1, 2, 3)).mean()
```

**要点：**
- **不是** diffusion 的 ε-prediction，而是 **flow matching 的 v-prediction**（预测「从噪声指向数据」的速度场）
- 时间步 `t` 用 **logit-normal** 采样（`P_mean=-0.8, P_std=0.8`），偏向中间时间步
- 损失就是**逐像素 L2（MSE）**，在 batch/通道/空间上平均

---

## 2. 优化器：AdamW

`lora_finetune_jit.py:195-196`

```python
param_groups = misc.add_weight_decay(model_without_ddp, args.weight_decay)
optimizer = torch.optim.AdamW(param_groups, lr=args.lr, betas=(0.9, 0.95))
```

| 参数 | 值 | 来源 |
|------|-----|------|
| 算法 | **AdamW** | 固定 |
| betas | **(0.9, 0.95)** | 固定（注意 β₂=0.95，比 PyTorch 默认 0.999 小） |
| eps | 1e-8 | PyTorch 默认 |
| weight_decay | **0.0** | `--weight_decay` 默认 0（对 LoRA 无衰减） |

> **不是 SGD，也不是 RMSprop。**

---

## 3. 学习率：按 batch 线性缩放 + warmup

### 3.1 基础 lr 缩放（`lora_finetune_jit.py:189`）

```
lr = blr × effective_batch_size / 256
```
- `blr`（base lr）默认 **5e-5**（`main_jit.py:150`）
- `effective_batch_size = batch_size × world_size`

**举例（本项目实测）：**

| batch_size | eff_batch | Actual lr |
|-----------|-----------|-----------|
| 4（GTX 1060）| 4 | **7.81e-07** |
| 8 | 8 | 1.56e-06 |
| 256 | 256 | 5.00e-05 |

### 3.2 调度（`util/lr_sched.py`）

```python
if epoch < warmup_epochs:      # 默认 warmup_epochs = 5
    lr = lr × epoch / warmup_epochs          # 线性 warmup
else:
    lr = lr if lr_schedule == "constant"     # 默认 constant（恒定）
    # 或（--lr_schedule cosine）
    lr = min_lr + (lr - min_lr) × 0.5 × (1 + cos(...))   # 半周期余弦退火
```

- **warmup**：默认 **5 轮**线性升温（逐 iteration 调用，`engine_jit.py:42`）
- **warmup 后**：默认 `lr_schedule="constant"` → **恒定 lr**
- 引擎也支持 `cosine`（半周期余弦退火，衰减到 `min_lr`）
- 本项目已通过 `config.jsonc` 的 `lr` / `lrSchedule` / `minLr` 透传（见 §3.3）

### 3.3 ⚠️ 小显存用户的坑

公式里要**除以 256**。当 batch 只有 4 时：

```
Actual lr = 5e-5 × 4/256 = 7.81e-7      ← 比标准小 64 倍
```

**后果：等效学习率被大幅压低**。

**缓解手段（已透传，改 `config.jsonc` 即可）：**
- `lr`：填**绝对 lr**（引擎 `--lr`，会覆盖上面的缩放公式）；留空 = 走 `blr × batch/256`
- `lrSchedule` + `minLr`：改成 `cosine`，让后期 lr 衰减下来

**⚠️ 实测结论见 [docs/training-experiments.md](training-experiments.md)：**

batch=4 + 恒定 lr 会让 loss 陷入**极限环**（周期约 10 轮，在 0.0328~0.0358 之间规律震荡，
"哪轮最好"纯属偶然）；改 `cosine` 后曲线变单调下降、best_loss 降 27.7% ——
但**字形质量并未同步变好**，所以**不能只凭 loss 挑模型**。

---

## 4. LoRA 微调配置

| 项 | 值 | 来源 |
|---|-----|------|
| rank `r` | **32** | `config.jsonc: loraR` |
| alpha | **32** | `config.jsonc: loraAlpha` |
| dropout | 0.0 | 引擎默认 |
| targets | `qkv,proj,w12,w3` | `config.jsonc` |
| 注入位置 | 48 个 Linear 层 | 引擎日志 |
| 可训练参数 | **5.487 M** | 引擎日志 |

**关键：** 只训 LoRA 旁路参数，ViT 主干**冻结**（`mark_only_lora_as_trainable`），所以 6GB 显存也能微调。

---

## 5. 其他训练细节

| 项 | 设置 | 说明 |
|---|------|------|
| **混合精度** | `torch.amp.autocast('cuda', dtype=torch.bfloat16)` | `engine_jit.py:62` |
| **梯度累积** | ❌ 无 | 无 `accum` 逻辑 |
| **梯度裁剪** | ❌ 无 | 无 `clip_grad_norm_` |
| **EMA** | ❌ 已禁用 | `model.update_ema = lambda: None`（`lora_finetune_jit.py:145`），故 `save_model_no_ema` |
| **分布式** | 支持 DDP，本项目单卡（`world_size=1`）| |
| **num_workers** | 0（本项目设置）| Windows 下更稳 |

---

## 6. 条件与 CFG（classifier-free guidance）

**训练时的条件（labels）**：`(font_labels, char_labels, style_images, content_images)`

- `drop_labels`（`denoiser.py:49-59`）：以 `label_drop_prob=0.1` 概率把条件置为「空」，用于训练 CFG
- 即：10% 的样本学「无条件生成」，90% 学「有条件生成」

**CFG 强度（guidance scale）在训练/生成两侧不同：**

| 阶段 | cfg |
|------|-----|
| 训练 | `2.6`（`config.jsonc: cfg`，仅记录/采样用）|
| 生成 | `4.0`（`gen_chars.py: CFG`）|

生成时按 `v = v_uncond + cfg × (v_cond − v_uncond)` 组合。

---

## 7. 采样生成（推理）

`generate_chars.py` + `denoiser.generate()`

| 项 | 值 |
|---|-----|
| 采样器 | **Heun**（`--sampling_method heun`）|
| 步数 | **50**（`--num_sampling_steps 50`）|
| CFG | 4.0 |
| 输出尺寸 | 256×256 |
| 批量 | ≤4（GTX 1060）|

Heun（2 阶 Runge-Kutta）比 Euler 精度高，代价是每步需 2 次前向。

---

## 8. 本项目实际取值汇总

**引擎收到的参数**（`utils/train_manager.py:start_training` 构造）：

```
--model JiT-B/16
--num_fonts 1000          # 必须 ≥ 预训练权重的 1000 类
--num_chars 200000
--max_chars_per_font 10000
--lora_r 32 --lora_alpha 32 --lora_targets qkv,proj,w12,w3
--epochs <目标总轮次>
--batch_size 4            # config.jsonc: batchSize
--cfg 2.6
--sampling_method heun --num_sampling_steps 50
--num_workers 0
--save_last_freq 1        # 每轮存 checkpoint-last
```

**未透传、走引擎默认值的参数：**

| 参数 | 默认值 | 含义 |
|------|--------|------|
| `--blr` | 5e-5 | base lr（缩放公式的基数）|
| `--warmup_epochs` | 5 | 线性 warmup 轮数 |
| `--lr_schedule` | `constant` | warmup 后恒定 lr |
| `--min_lr` | 0 | 仅 cosine 调度用 |
| `--weight_decay` | 0.0 | AdamW 权重衰减 |
| `--P_mean` / `--P_std` | -0.8 / 0.8 | 时间步 logit-normal 采样 |
| `--t_eps` | 0.05 | 速度换算的分母下限 |
| `--label_drop_prob` | 0.1 | CFG 条件丢弃概率 |

---

## 9. 调参建议

| 症状 | 可调项 | 说明 |
|------|--------|------|
| 收敛慢 / 欠拟合 | **`blr` 调大**（或传 `--lr`）| batch=4 时 lr 被压到 7.8e-7，可提到 1e-5 量级 |
| 风格不够像 | `loraR` 调大（32→64）、增加轮次 | 低秩容量 + 训练量 |
| 过拟合（生成字崩坏）| 减少轮次 / 降 `loraR` | |
| 显存不足 | `batchSize` 降到 2 | 6GB 卡上限 4 |
| 生成不贴风格 | 生成侧 `CFG` 调大（4.0→5~7）| |
| 生成多样性差 | 生成侧 `MULTIPLIER` 调大（多采样筛选）| |

> **备注：** `blr` / `warmup_epochs` / `lr_schedule` 目前**未从 config.jsonc 透传**——如需调整，需在 `utils/train_manager.py:start_training` 的 `cmd` 里补参数。
