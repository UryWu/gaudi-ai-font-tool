# TTF 渲染空白诊断与修复（2026-09-16）

> 背景：用户报告 font/my_personal_font.ttf 里部分字形在 PIL 默认 mode='L' 下渲染成空白。
> 本文档是诊断过程和修复方案的记录，方便后续查阅。

## ⚠️ 第二轮修复（2026-09-16 晚）："中"字的内容也是错的

`uni4E2D.png` **根本不是"中"字**——是"甲"字。猜测是导出时码点错配（filename 标 U+4E2D，但内容是甲的笔画）。

dev 删了那个甲字 PNG + 历史副本，让 `collect_entries` 按字典序选 `uni4E2D_01.png` 当"中"的源。重建后字体里"中"字实测渲染正常（ink=1206 @ 96px）。

**我方动作**：去掉 `--exclude-file uni4E2D.png`（之前那个 exclude 实质上是排除了"甲"字，现在甲字已经删了）。dev 后续若再有内容错误的字形，会先排查内容再考虑技术 exclude。

## ⚠️ "中"字问题留个记录（防再次混淆）

- 全仓合并目录里 `uni4E2D_01.png ~ uni4E2D_12.png` 才是"中"的合法变体（不同手写风格样本）
- 旧 `uni4E2D.png`（甲字）已删
- 之前一直用 `--exclude-file uni4E2D.png` 排的是甲字（实际从来没用"中"的旧图）
- 现在 base 直接用 `uni4E2D_01.png` 渲染干净的"中"

## ⚠️ 仍空白的 5 个字符（不是闭口字母）

dev 第二轮修完后, 我把 26 大小写字母 + 10 数字 + 5 特殊符号全扫了一遍:

| 状态 | 字符 |
|---|---|
| ✅ 全部正常 | `a b c d e f g h i j k l m n o p q r s t u v w x y z A B C D E F G H I J K L M N O P Q R S T U V W X Y Z 0 1 2 3 4 5 6 7 8 9`（共 62）|
| ❌ 完全空白 ink=0 | **`@` `#` `&` `?` `!`**（5 个符号, 不是闭口字母）|

**关键确认**：所有**闭口字母** (a/d/e/g/o/p/q/A/D/O/P/Q/R + 0/4/6/8/9) 都渲染正常了 — winding 修复生效.

仍空白的 5 个 (`@ # & ? !`) 是符号/标点:
- 验证: `ls G:\...\all_characters\{uni0040,uni0023,uni0026,uni003F,uni0021}.png` → 全部**不存在**
- 结论: **不是 bug, 是数据缺失** — 用户从未手写过这 5 个符号, 合并目录里没收
- 若想渲这些字符: 先手写 → preprocess 导出 → dev 合并

## ⚠️ 第三轮 (2026-09-16 晚): 用户补齐 5 个符号

会话 `6d59596f438cd47b76ecbba2dc71d43f` 新导出 5 张:
  `uni0040 @` `uni0023 #` `uni0026 &` `uniFF1F ？` `uniFF01 ！`

注意: 用户给的是**全角 `？` `！`** (U+FF1F, U+FF01), 不是半角 `?` `!` (U+003F, U+0021).
经核实: 用户 3 篇文档里出现的 `?` `!` 全部为全角, 所以给全角版本刚好覆盖需求.
如果将来需要半角 `?` `!`, 还得再补.

dev 把 5 张合并后重建 base TTF:
- PNG: 3161 → **3166** (+5)
- 唯一字根: 1457 → **1462** (+5)
- `？` `！` 因为已有旧变体, 合并后变成了 `uniFF1F_02.png`, `uniFF01_01.png` (旧变体保留共存)
- 旧版 `@` `#` `看` `一` 是「列扫描矩形 1-像素宽」, 96pt 渲染亚像素 → 散点陷阱
- dev 这次把 PROBE_SIZE 从 96 调到 64 + threshold=50, 解决了散点漏报

### 我方脚本同步升级

`scripts/check_glyph_render.py` 阈值从 `ink > 0` 改到 `ink >= 50`:
- 与 dev 的 fallback 阈值对齐
- 能拦住「细笔画字符亚像素散点」陷阱 (之前 `ink=63`/`76` 都漏报)
- 之前几轮 TTF 自报 `0 失败` 其实都有视觉散点 bug — 现在能拦住

### 端到端实测 (重新出图)

重 build 后字体:
- `font/my_personal_font.ttf` 8.1 MB / 1462 字
- 5 个新符号实测 @=831, #=732, &=813, ?=360, !=293 → 全部正常 ✅

仍空白的 (不在 all_characters/ 里, 用户没补):
- `%` (U+0025): 用户在新批次里**删了** (`%` 不在文档里)
- `+` (U+002B), `÷` (U+00F7): 用户**没补** (也不在文档里)
这 3 个不算 bug, 是数据缺失.

## 时间线

| 时间 | 事件 |
|---|---|
| 9-15 | 用户新建 12 字形补字（— ’ 等），发现新字渲染空白 |
| 9-15 22:06 | 12 个字形实测 `PIL getmask(mode='L')` 全部 ink=0 |
| 9-15 22:30 | **本仓库提交 `check_glyph_render.py`** 体检工具 |
| 9-15 22:40 | dev 第一次修：用 `cv2.findContours + approxPolyDP`，per-glyph fallback |
| 9-15 23:00 | dev 自报 17 个 fallback，但实测 "D / o / 8" 变实心黑块、"’" 仍空白 |
| 9-16 07:00 | dev 二次修：winding 双反转修正 + probe 阈值放宽（ink<50 触发）|
| 9-16 09:30 | **fallback 命中 571/1457**，全部 0 视觉失败 |

## 根因（两层）

### 第 1 层：FreeType autohint 把"共边矩形"压成零高度

dev 的 `build_personal_ttf.py` 用「按列扫描矩形」算法生成字形轮廓：

```
对每列 y 区间，生成 4 点矩形: (x_left, y_top, x_right, y_bottom)
```

相邻矩形**首尾点重合**（x_right = 下一列的 x_left）。

**问题**：FreeType 的自动 hinting 在某些字形上**把这种共边轮廓压成零高度**——导致 `PIL getmask(mode='L')` 返回空 bitmap（ink=0）。

**复现**：换 `FT_LOAD_NO_HINTING` / `FT_LOAD_NO_AUTOHINT` 后立即恢复 ink>0。

### 第 2 层：winding 方向双反转

dev 第一轮修复时同时引入 cv2 fallback，但**注释里**写：

> "OpenCV 在 y-down 坐标下，外轮廓是逆时针遍历的"

这是**错的**——OpenCV（CHAIN_APPROX_NONE）实际外轮廓是**顺时针**、内孔是**逆时针**。

dev 的修复代码：

```python
# y-flip 把 CW → CCW (外), CCW → CW (内)
# 然后又对 hole 多做 reversed()  "修正 winding"
pts = [(x_img, y_img) ...]                 # y-down
pts = flip_y(pts)                          # y-up
if is_hole:
    pts = list(reversed(pts))               # 再翻一次
```

结果：外轮廓 CCW + reversed CCW = **CW**（不对），洞也类似 —— **TrueType 非零环绕**认为内外同向 → 整字填实心。

dev 第二轮修正：删掉 `reversed(pts)`，让 y-flip 单独处理方向：

| 坐标 | 外轮廓 | 内孔 |
|---|---|---|
| OpenCV y-down | CW (signed_area > 0) | CCW (signed_area < 0) |
| y-flip → y-up | **CCW** | **CW** |
| TrueType 要 | CCW 或 CW（外） | **必须反向**（内） |

去掉 reversed 后：外 CCW + 内 CW —— 内外反向 ✅。

### 第 3 层：probe 阈值过宽松

dev 的 `probe_glyph_ink()` 之前用 `ink == 0` 触发 fallback。**问题**：

- 封闭轮廓字（a/d/g/p/q/A/O/P/Q/R/0/4/6/9）因 autohint 崩塌，最终字体里渲出 **ink=1~33**（视觉空白但 ink>0）
- probe 在迷你字体里给 ink>0（fallback 不触发）
- 修复：`ink < FALLBACK_INK_THRESHOLD(50)` 触发 fallback
- CJK 实心字（看/中/党/的 等）实测 ink > 500 → 不误伤 ✅

## 最终数字

| 阶段 | fallback 命中 | 0 失败 |
|---|---:|:---:|
| 第一轮（ink==0）| 17 | ❌ |
| 第二轮（winding 双反）| 17 | ❌（实心块）|
| 第三轮（winding 修 + 阈值放宽）| **571 / 1457** | ✅ |

**取舍**：545 个字符失去了「手写台阶质感」（dev 改用 cv2 轮廓算法），换取 0 个视觉失败。

如果觉得 571 太多，可把 `FALLBACK_INK_THRESHOLD` 上调（如 100/200）—— 但 26（之前实测 12+14）是绝对下限，少于这个一定漏判。

## 我方 (gaudi-ai-font-tool-dev) 的动作

- 提交 `check_glyph_render.py`：能用 `PIL getmask` 一键扫所有字形
- 给三个脚本加 `--exclude` / `--exclude-file`（之前已提交）
- **无代码改动需要**：bug 完全在 dev 那边；我方只是把 dev 修好的 TTF 拷过来用

## 给未来自己的提醒

1. **看图判断字形时**：
   - 用 `font.getmask(ch)` 算 `numpy` 数组 + 看 `fill_ratio = ink / bbox_area`
   - 不要靠抗锯齿渲染（draw.text）看"暗不暗"判断
   - `ink == 0` ≠ 字符渲染不出来，可能只是 probe 阈值太严

2. **fallback 阈值调试顺序**：
   - winding 错（实心块）→ 看 200px 大字号更明显
   - probe 漏判（空白字）→ 跑 `check_glyph_render.py @ 80px`，看 ink < 50 的字形
   - **两者必须同时修**——只修一个会暴露另一个

3. **数字核对**：
   - dev 自报 17，实际命中 26（含原报告的 12 + 我后来补的 14 个封闭轮廓字）
   - 26 是绝对下限，少于这个一定漏判

4. **远程协作流程**：
   - dev 修完说"修好了"不能立刻信 —— 必须本地实测 `check_glyph_render.py`
   - 出图肉眼对照"修复前 vs 修复后"
   - 这次 winding 错就是 dev 第一次"修好了"我实测才发现的
