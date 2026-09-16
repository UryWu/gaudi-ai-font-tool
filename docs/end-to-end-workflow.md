# 端到端工作流：从手写到最终图（2026-09-16）

> 本文把**整条工具链**串起来：从 preprocess 那边手写 → 合并 → 生成 TTF → 生成含变体的渲染副本 → handwriter 出图。
> 配套：[`merge-2026-09-14.md`](merge-2026-09-14.md)（合并）、[`font-variants.md`](font-variants.md)（变体机制）、[`TTF-修复说明.md`](TTF-修复说明.md)（字体坑）

## 完整链路

```
【0】手写 (paper)
  ↓
【1】gaudi-font-preprocess (端口 7500)
   - 拍照 → /adjust → /scale → /annotate → 导出
   - 产出: data/sessions/<会话>/exported/<批次>/*.png + CSV + source_map.json
  ↓
【2】合并到 all_characters/
   - gaudi-font-preprocess-dev 那边跑 merge_session_to_all.py
   - 这步我们**不动**, 等 dev 通知合并结果
  ↓
【3】重生 base TTF
   - gaudi-font-preprocess-dev 那边跑 build_personal_ttf.py
   - 产出: G:\...\gaudi-font-preprocess\font\my_personal_font.ttf
  ↓
【4】拷到我方项目 + build 变体字体 (我方)
   cp .../my_personal_font.ttf G:\...\gaudi-ai-font-tool\font\
   python scripts/build_variant_ttf.py \
       --base-ttf font/my_personal_font.ttf \
       --images-dir G:\...\gaudi-font-preprocess\data\sessions\all_characters \
       --out font/my_personal_font_variants.ttf \
       --map-out font/variant_map.json
  ↓
【5】生成渲染副本 (我方)
   python scripts/make_variant_text.py \
       原稿.txt --map font/variant_map.json \
       --out 渲染副本.txt --seed 42
   - 原稿**不动**, 输出副本含 PUA 码点
   - 同一原稿换 --seed 得到不同副本 (随机选 PUA 变体)
  ↓
【6】用副本出图 (handwriter)
   - **不要**手拷字体到 handwriter/fonts/ (会污染 handwriter 仓, 且 .gitignore 屏蔽)
   - 由**用户**用 handwriter 提供的 `install_external_font.ps1` 注册 (路径引用, 不复制):
     ```powershell
     cd G:\Projects\projects_ai\handwriter
     .\install_external_font.ps1 -Path "G:\...\gaudi-ai-font-tool\font\my_personal_font_variants.ttf" -Kind variant -Name "我的书法 (变体)"
     .\install_external_font.ps1 -Path "G:\...\gaudi-ai-font-tool\font\my_personal_font.ttf" -Kind normal -Name "我的书法 (主字形)"
     ```
   - 注册表位置: `handwriter\Parameter\external_fonts.json` (只记录路径, 不复制)
   - 启动 handwriter v2.0 → 字体下拉看到 `[变体] 我的书法 (变体)` → 选它
   - 加载**渲染副本.txt** (不是原稿) → 渲染出图
   - 字体文件始终留在 `gaudi-ai-font-tool/font/` (已 .gitignore, 不进任何仓库)
```

## 典型路径

### 路径 A: 我 (用户) 已经把字写完, 现在只想出图

```bash
# 1. 等 dev 合并 + 重 build
#    (他那边会发消息告诉你路径, 你确认新 .ttf 文件已更新)

# 2. 拷到我方
cp G:\...\gaudi-font-preprocess\font\my_personal_font.ttf \
   G:\...\gaudi-ai-font-tool\font\

# 3. 重 build 变体字体
cd G:\...\gaudi-ai-font-tool
python scripts/build_variant_ttf.py \
    --base-ttf font/my_personal_font.ttf \
    --images-dir G:\...\gaudi-font-preprocess\data\sessions\all_characters \
    --out font/my_personal_font_variants.ttf \
    --map-out font/variant_map.json

# 4. 验证
python scripts/check_glyph_render.py font/my_personal_font.ttf
python scripts/check_glyph_render.py font/my_personal_font_variants.ttf
# 期望: 全部 ✅ 0 失败

# 5. 生成渲染副本
python scripts/make_write_list.py --font font/my_personal_font.ttf \
    --doc "F:\Files\入党\入党积极分子思想汇报_3000字左右.md" \
    --out 书写清单_思想汇报.csv  # 如果需补字, 输出清单; 否则打印 ★ 需补字 = 0
python scripts/make_variant_text.py 原稿.txt --map font/variant_map.json \
    --out 渲染副本.txt --seed 42

# 6. 拷给 handwriter
cp font/my_personal_font.ttf font/my_personal_font_variants.ttf \
   G:\...\handwriter\fonts\

# 7. 启动 handwriter v2.0 → 选字体 "我的书法 变体" → 加载渲染副本.txt → 渲染
```

### 路径 B: 我 (用户) 还没补字, 想看缺什么

```bash
# 1. 看缺口
python scripts/char_freq.py <文档> --font font/my_personal_font.ttf
# → 输出覆盖率 + 缺失字清单 (CSV + 文本)

# 2. 出书写清单
python scripts/make_write_list.py --font font/my_personal_font.ttf \
    --doc <文档> --out 书写清单.csv
# → 输出该文档缺哪些字 + 每个字写几种 (按字频分档)

# 3. 在纸上写, 按"同一个字连着写"顺序 (同字相邻, preprocess OCR 自动归并为变体)

# 4. preprocess 那边: 拍照 → /scale → /annotate → 导出

# 5. 让 dev 合并 + 重 build (回到路径 A)
```

## 角色分工

| 步骤 | 谁负责 | 工具 |
|---|---|---|
| 1. 手写 + 拍照 | 用户 | 纸 + 手机 |
| 2. 切割/缩放/标注/导出 | **用户**操作 | `gaudi-font-preprocess` (端口 7500) |
| 3. 合并到 all_characters | dev 那边 | `merge_session_to_all.py` |
| 4. 重 build base TTF | dev 那边 | `build_personal_ttf.py` |
| 5. 拷 + 重 build 变体 + 验证 | **我** (gaudi-ai-font-tool-dev) | `build_variant_ttf.py` + `check_glyph_render.py` |
| 6. 生成渲染副本 | **我** | `make_variant_text.py` |
| 7. 用副本出图 | **用户**操作 | `handwriter v2.0` (端口 GUI) |

## 已踩过的坑（必读）

### 1. TTF 字形渲染异常

如果 `check_glyph_render.py` 报失败, 不要相信 `ink > 0` 的旧判断 —— 现在阈值是 `ink >= 50`。
详见 [`TTF-修复说明.md`](TTF-修复说明.md)。

如果 dev 改了字体算法 (比如又改了 `build_personal_ttf.py`), 也要重 build base + 重 build 变体。

### 2. 字符内容错误

preprocess 导出时**码点 ↔ 字** 可能错配 (例如 `uni4E2D.png` 实际是"甲"字不是"中"字)。**先看字形, 再看文件名/码点**。
详见 [`TTF-修复说明.md`](TTF-修复说明.md) 第二轮。

### 3. 撞名

合并到 all_characters/ 时, 同字根的 PNG 都按字典序排 (`uni7684.png` 排在 `uni7684_01.png` 之前), 同码点只取第一张。
所以 `uni4E2D.png` 是错的"甲", dev 删了它, 让 `uni4E2D_01.png` 顶上。

如果你的图片里有两张同字根的, 删错了一张, 字符会变成别的字 → **检查合并目录里删剩了什么**。

### 4. 散点陷阱 (历史教训)

build_personal_ttf.py 用「按列扫描矩形」法, 1-像素宽矩形在 96pt 渲染时亚像素, 抗锯齿吃掉 → 视觉散点 (但 PIL getmask 给 ink=63/76, 看似正常)。

`check_glyph_render.py` 默认阈值已调到 50, 能拦住。但**阈值不是万能的**, 重要交付前一定要出图肉眼检查。

### 5. 半角 vs 全角标点

用户文档里 `?` `!` **实际是全角** (U+FF1F, U+FF01), 不是半角 (U+003F, U+0021)。
preprocess / 用户补字时**按文档实际使用形式补** (你的文档用什么就补什么)。

## 已知字库覆盖

| | 数 |
|---|---|
| 字体字符数 | **1462** |
| 变体数 | **1707** PUA |
| 覆盖率 (思想汇报) | **100%** (0 待补字) |
| 覆盖率 (心得+申请书) | **100%** (0 待补字) |
| 缺的符号 (不在合并目录里) | `% + ÷` (用户文档里 0 次, 不影响) |

## 流程图 (角色视角)

```
┌─────────────────────────────────────────────────────────┐
│ 用户操作                                                     │
│   手写 → preprocess 端口 7500 → 导出 PNG                    │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│ gaudi-font-preprocess-dev (另一个项目里的协作 AI)           │
│   merge_session_to_all.py → build_personal_ttf.py          │
│   产出: .../font/my_personal_font.ttf                     │
└─────────────────────────────────────────────────────────┘
                          ↓ (拷 + 等 dev 重 build)
┌─────────────────────────────────────────────────────────┐
│ 我 (gaudi-ai-font-tool-dev)                                │
│   build_variant_ttf.py → check_glyph_render.py              │
│   make_variant_text.py → 生成 渲染副本.txt                  │
└─────────────────────────────────────────────────────────┘
                          ↓ (拷渲染副本 + 字体到 handwriter)
┌─────────────────────────────────────────────────────────┐
│ 用户操作                                                     │
│   handwriter v2.0 → 选字体 → 加载 渲染副本.txt → 渲染        │
└─────────────────────────────────────────────────────────┘
                          ↓
                       成品图 (PNG)
```

## 我的建议

第一次出图建议走路径 A (一字不动, 直接拿现成的字体出图), 验证全链路通顺。
之后想补字再走路径 B。
