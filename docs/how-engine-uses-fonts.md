# 训练基础概念（TTF / ref 字 / 引擎数据契约）

> 给「第一次接触 AI 字体训练」的读者准备的速读文档。配合 [make-personal-font.md](make-personal-font.md) 一起看，先理解这些概念再看具体步骤。

---

## 1. TTF 是什么？怎么合成？

**TTF = TrueType Font**，一种字体文件格式（Windows 里就是 `.ttf` 后缀那个）。
一个 TTF 文件由两部分组成：

| 组成 | 作用 |
|------|------|
| **矢量轮廓** | 每个字符的数学曲线（不是像素，是公式） |
| **字符→字形映射表（cmap）** | 告诉系统「U+4E00 码点对应哪个字形」 |

矢量优势：放大缩小都不糊；渲染时按目标尺寸栅格化成像素。

### 格式对比

| 格式 | 内容 | 你手上有吗 |
|------|------|-----------|
| **`.png`** | 位图（像素） | ✅ 319 张 `scaled_NNNN.png`，512×512 灰度 |
| **`.ttf`** | 矢量轮廓 + cmap | ❌ 还没有 |

### 怎么合成 TTF

经典两步：

**步骤 1：准备字形（每个字符的矢量路径）**
- FontLab / FontForge GUI 手工描字
- 从 PNG 自动矢量化（potrace，有损）
- 从 TTF 渲染引擎（PIL `ImageFont.truetype`）输出——最常见

**步骤 2：用 fontTools 打包**

```python
from fontTools.fontBuilder import FontBuilder

fb = FontBuilder(1000, isTTF=True)
fb.setupGlyphOrder([...])                          # 字形名列表
fb.setupCharacterMap({0x4E00: "uni4E00", ...})     # cmap
fb.setupGlyf({...})                                # 矢量轮廓
fb.setupHorizontalMetrics({...})                   # 字宽
fb.setupHorizontalHeader()
fb.setupNameTable({"familyName": "我的书法", "styleName": "Regular"})
fb.setupOs2()
fb.setupPost()
fb.save("我的字库.ttf")
```

### 💡 关键洞察：合 TTF 其实是绕路

训练用的引擎 `FontSrcTargetRefsDataset`（引擎侧 `main_jit.py:24`）**直接吃图片目录，不吃 TTF**。

- **方案 A（绕路）**：PNG → 合成 TTF → 引擎再渲染 → 训练（多此一举、矢量化有损）
- **方案 B（直路）**：PNG → 直接拼成 1024×256 复合图 → 训练 ✅

**所以本项目训练个人字库，TTF 中间步骤完全不需要。** 合成 TTF 适合「把字库给别人用」（装到系统里、嵌入软件），不适合「喂给 AI 训练」。

---

## 2. ref 字是什么？什么作用？

### 训练数据的复合图结构（1024×256）

```
┌────────────────┬────────────────┬──────────┬──────────┐
│                │                │          │          │
│   source       │   target       │ ref grid │ ref grid │
│   (256×256)    │   (256×256)    │ 0..3     │ 4..7     │
│                │                │ (128 ea) │ (128 ea) │
│                │                │          │          │
└────────────────┴────────────────┴──────────┴──────────┘
0                256              512        768       1024
```

- **source**：X 的标准字形（来自 `default.ttf`），告诉模型「X 是哪个 unicode」
- **target**：X 的个人字形（你的手写），告诉模型「X 在你的字库里长啥样」
- **ref grid**：8 个 128×128 字格，每格放**同一种字体的另一个字**（风格参考）

### ref 怎么用（看 `main_jit.py:75-96` 的 `__getitem__`）

```python
ref_global_idx = random.randint(0, 7)        # 0..7 随机抽 1 格
grid_idx = ref_global_idx // 4                # 0 或 1（左/右两块）
ref_idx = ref_global_idx % 4                  # 0..3（块内位置）
ref = img.crop((512 + grid_idx*256,
                (ref_idx // 2) * 128,
                512 + grid_idx*256 + 128,
                (ref_idx // 2 + 1) * 128))
```

模型在生成 target 时，**从 8 格 ref 里随机抽 1 格当风格锚点**。

### 直观比喻

> - **target** = 要生成的字（X）
> - **source** = X 的标准写法（告诉模型 X 是哪个字）
> - **ref** = 「这字体的另 8 个已知字」（告诉模型「这种字体的笔锋、间架、风格是这样的」）

### 8 个 ref 字怎么选

- 训练时每张图随机抽 1 格，**8 格是同一种字体的不同字就行**，具体哪 8 个无所谓
- 推荐：选 8 个常用字（「永和人之大…之类」），且都在 319 集里最稳
- 不在 319 集里的字：用 `default.ttf` 渲染那 8 个补进 ref 网格（兜底）

---

## 3. 引擎数据契约（读源码总结）

引擎 `FontSrcTargetRefsDataset`（`main_jit.py:24`）的硬要求：

| 契约项 | 要求 |
|--------|------|
| 根目录结构 | `data_path/<font_dir>/NNNNN_字.png`（每个子目录 = 一种字体） |
| 文件名 pattern | `{int}_{char}.png`，int 是 0..N-1 连续编号 |
| 复合图尺寸 | 1024×256 RGB，3 块严格切：source(0,0,256,256) / target(256,0,512,256) / ref 8格 |
| char_idx 用途 | **不当条件用**——只算 `num_chars = max+1`；字符 unicode 来自 source 图 |
| 字体数 (num_fonts) | ≥ 1（至少一个子目录） |
| test.npz | 训练不消费，只过门禁；style_content_images 渲染个空 TTF 写进去即可 |

### 重要结论

1. **PNG 直接喂，TTF 中间步骤多余**（已重复 3 遍了，因为这是最关键的反直觉点）
2. **char_idx 不映射 unicode**——所以文件命名顺序随便，只要 0..N-1 连续
3. **source 必须来自一个真 TTF**（default.ttf 即可），因为模型通过 source 知道「要生成哪个字」

---

## 4. 个人字库训练路径对比

| 路径 | 步骤 | 优劣 |
|------|------|------|
| ❶ PNG → 拼复合图 → 训 | 3 步 | ✅ 直路、本项目主推 |
| ❷ PNG → 合成 TTF → 训 | 4 步 | ❌ 绕路、矢量化有损 |
| ❸ TTF → 引擎渲染 → 训 | 3 步 | 适用「已有完整矢量 TTF」场景 |

**本项目（gaudi-ai-font-tool）走路径 ❶。**

---

## 5. 实战：本项目的训练入口

`utils/train_manager.py` 现已支持两种 prepare 模式：

| 模式 | 触发 | target 来源 |
|------|------|------------|
| 传统 | `ref_font` 有值且 `images_dir` 缺省 | `GlyphRenderer(ref_font).render(char)` |
| 注入 | `images_dir` 有值 | 直接读 `images_dir/uniXXXX_字.png` |

新加的字段（前端可选用）：
- `images_dir`：外部已标好的 PNG 目录（路径）
- `labels_csv`：可选，CSV 含 filename/character；缺省按 PNG 文件名解析 unicode

详见 [make-personal-font.md](make-personal-font.md) 流程。
