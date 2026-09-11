# 字体变体：让同一个字有多种写法

> 手写素材里同一个字往往写了多遍（「的」25 种、「党」13 种…）。但 **TTF 的 cmap 是一对一映射**
> （一个码点只能对应一个字形），所以合成字体时每种写法只能留一个，**其余全部丢失**。
> 本文说明怎么把这些变体装进一个 TTF，并在渲染时按需调用。
>
> 配套：`docs/make-personal-font.md`（制字全流程）、`docs/how-engine-uses-fonts.md`（TTF 基础概念）

## 1. 问题：变体在 PNG→TTF 这一步被丢掉

实测现有素材（`gaudi-font-preprocess` 导出）：

| | 数量 |
|---|---|
| PNG 总数 | **318** |
| 唯一字符 | **152** |
| 有多种写法的字符 | **50**（的 25、党 13、`，`13、中 12、国 11、共 7…）|
| 因此多出来的写法 | **166** |
| 合成 `my_personal_font.ttf` 后保留 | 152 个字形 —— **166 种写法丢了** |

变体信息只存在于文件名里（`uniXXXX.png` = 第 1 种，`uniXXXX_01.png` = 第 2 种…），
代码路径（`utils/import_images.py:_scan_images_dir`）的正则一律带 `(?:_\d+)?`，**会把序号丢掉**。

## 2. 解决：把变体挂到 Unicode 私用区（PUA）

**PUA = `U+E000–U+F8FF`，共 6,400 个码点**，Unicode 专门留给私用、不分配给任何真实字符。
把变体字形挂上去：

```
cmap:
  U+7684  → 的·第 1 种写法      ← 正常码点，默认写法
  U+E000  → 的·第 2 种写法      ┐
  U+E001  → 的·第 3 种写法      │ 都是普通字形，
  ...                           │ 没有任何特殊机制
  U+E018  → 的·第 25 种写法     ┘
  U+4E00  → 一
  U+E019  → 一·第 2 种写法
```

**全部在同一个 TTF 里，不需要多个字体文件。**

### 为什么不走 Unicode 官方的变体选择符 IVS

IVS（`U+7684 U+FE00` → 变体的官方机制）看起来更"标准"，但**实测 handwriter 用不了**：

1. 它 `ImageFont.truetype(path, size)` 没传 `layout_engine` → Pillow 默认 `LAYOUT_BASIC`，C 层对每个码点单独查 cmap，**不查 UVS 表**
2. 它**逐字** `draw.text(char)`（每个字单独一次调用）→ 即使引擎支持整形，变体序列也会被拆开
3. 全文件没有任何变化选择符相关逻辑

实际效果：`的` + `U+FE00` 会渲染成 `的` 再叠一个 `.notdef` 豆腐块，**绝不会**得到变体字形。

## 3. 工具链（三个脚本）

| 脚本 | 作用 |
|---|---|
| `scripts/build_variant_ttf.py` | PNG 素材 + 基础字体 → **带 PUA 变体的新 TTF** + 变体映射表 |
| `scripts/make_variant_text.py` | 原稿 → **渲染副本**（把一部分字换成变体码点） |
| `scripts/make_write_list.py` | 算出**该补写哪些字、每个字写几种**（书写清单 CSV）|

### 3.1 构建带变体的字体

```bash
python scripts/build_variant_ttf.py \
    --base-ttf   font/my_personal_font.ttf \
    --images-dir "G:\...\exported\<时间戳>" \
    --out        font/my_personal_font_variants.ttf \
    --map-out    font/variant_map.json
```

**两个源、两种质量**：

- `--base-ttf` 提供**已有字形的现成轮廓，逐指令原样复制**（零质量损失）
- `--images-dir` 只用于**新增的变体**走矢量化

这样做是因为 base 字体是 FontLab/potrace 类工具的高密度描点产物（「的」有 3,044 个控制点），
而我们自己的矢量化只能做到数百点 —— 复制主字形可把质量风险**限制在新增的变体上**。

矢量化用已有依赖完成，**不需要新增任何库**：`cv2.findContours(RETR_CCOMP)` 提外轮廓+内孔 →
`cv2.approxPolyDP` 简化 → `TTGlyphPen` 写轮廓。`--epsilon` 默认 0.3（越小点越密、越接近 base 风格）。

> **不覆盖 `--base-ttf`** —— 那份字体被 `scripts/gen_chars.py` 的 `REF_FONT` 与 AI 流程引用。

### 3.2 生成渲染副本

```bash
python scripts/make_variant_text.py 原稿.txt \
    --map font/variant_map.json --out 渲染副本.txt --seed 42
```

对每个「有变体的字」，在 **[主字形 + 它的所有变体]** 中等概率随机取一个。
`--seed` 固定则输出可复现；换个数字得到另一版随机结果。换行与段落结构原样保留。

渲染副本可直接喂给 handwriter（它的 `fonts/` 只加载 `.ttf`，把新字体复制进去即可）。

## 4. ⚠️ 两个必须知道的限制

1. **渲染副本不再可读** —— PUA 码点在编辑器里是空白框、搜索"的"搜不到。
   所以**只在副本上做，原稿不要动**（脚本默认输出到另一个文件，且拒绝 `--out` 等于原稿）。
2. **只有写了多种写法的字才有变体**。当前只覆盖 50 个字符，其余 102 个字符只有一种写法。
   变体数量不是均匀的：出现越多的字越值得多写几种（见 `scripts/make_write_list.py` 的字频分档）。

## 5. 实测标定（写代码时别凭直觉）

构建过程中量出来的、容易踩坑的事实：

| 事实 | 数据 |
|---|---|
| **base 字体 advance = bbox宽度 + 侧边距** | 侧边距恒为 **21~22** 单位（152/152）。给新字形定 advance 时必须带上它，否则新字会比原字排得更紧 |
| **字形度量归一化规则** | 等比缩放装进 **1749 × 1659** 的箱、锚点 `(0, 102)`。该规则在 152/152 个字形上完全命中（±2 单位），用于 base 里还没有主字形的字 |
| **`is_cjk()` 不含 CJK 标点** | `CJK_RANGES` 没有 `。`(U+3002)、`，`(U+FF0C) 等。所以 `utils/charset_utils.get_font_chars()` 会漏掉它们 —— 判断「字库够不够用」要读**原始 cmap** |
| **base 字形的字距极紧** | `advance ≈ 墨迹宽度`，字与字之间几乎没有间隙（不是 bug，是 FontLab 那份字体的设计）。handwriter 的 `word_spacing` 参数可补 |
| **主字形质量未必最好** | 实测 `的`/`党` 的**主字形比变体更粗重、更糊**（笔画糊在一起），变体反而结构分明 |

## 6. 验证方法（改完代码怎么确认没坏）

```bash
# 1. 构建
python scripts/build_variant_ttf.py --base-ttf font/my_personal_font.ttf \
    --images-dir "<素材目录>" --out /tmp/v.ttf --map-out /tmp/map.json

# 2. 四项断言
python - <<'PY'
from fontTools.ttLib import TTFont
base, new = TTFont('font/my_personal_font.ttf'), TTFont('/tmp/v.ttf')
bm, nm = base.getBestCmap(), new.getBestCmap()
assert len(nm) == len(bm) + 166          # cmap 152 → 318
assert new['head'].unitsPerEm == base['head'].unitsPerEm
# 主字形轮廓必须逐指令一致（零损失）
from fontTools.pens.recordingPen import RecordingPen
bgs, ngs = base.getGlyphSet(), new.getGlyphSet()
for cp, gn in bm.items():
    a, b = RecordingPen(), RecordingPen()
    bgs[gn].draw(a); ngs[gn].draw(b)
    assert a.value == b.value, gn
# 变体 advance 必须等于其主字形
PY
```

再跑一次 `make_variant_text.py`（同 seed 两次输出字节应相同），把新字体丢进
`handwriter v2.0\fonts\` 出一页图肉眼确认。

**已有实测结果**（用现有 318 张素材）：

| 检查项 | 结果 |
|---|---|
| cmap 条目 | 152 → **318** ✅ |
| glyph 总数 | 153 → 319 ✅ |
| 主字形轮廓逐指令一致 | **152 / 152** ✅ |
| 主字形 advance/lsb 变化 | **0** ✅ |
| 变体渲染回图 IoU（vs 源 PNG）| 最低 **0.936**、中位 **0.965**、全部 ≥ 0.90 ✅ |
| 变体 advance = 主字形 advance | **166 / 166** ✅ |
| 主字形渲染逐像素差（vs 原字体）| **0** ✅ |

## 7. 完整工作流

```
【阶段 1】补字
  python scripts/char_freq.py <文档> --font <现有字库>          ← 看还差多少
  python scripts/make_write_list.py --font <现有字库> --doc <文档> --out 书写清单.csv
       ↓ 按清单手写（同一个字的多种写法连着写！）
       ↓ 拍照 → gaudi-font-preprocess（7500）切割/标注/导出

【阶段 2】建字体
  python scripts/build_variant_ttf.py --base-ttf <现有字库> \
      --images-dir <新导出的目录> --out <新字库>.ttf --map-out variant_map.json
  python scripts/char_freq.py <文档> --font <新字库>.ttf        ← 覆盖率应到 100%

【每次要渲染文章时】
  python scripts/make_variant_text.py 原稿.txt --map variant_map.json --out 副本.txt
       ↓ 副本.txt + 新字库 丢给 handwriter
```

> **为什么同一个字的多种写法要连着写**：这样过 preprocess 的 OCR 时，连写的同一个字会被识别成
> 同一字符，导出自动变成 `uniXXXX.png` + `uniXXXX_01.png`… **天然就是变体序列**，无需人工标注对应关系。
