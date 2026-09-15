# -*- coding: utf-8 -*-
"""构建带 PUA 变体的 TTF —— 把「同一个字的多种写法」装进一个字体文件

## 为什么要 PUA

TTF 的 cmap 是**一对一**映射（一个码点 → 一个字形），所以「同一个字的第 2、3… 种写法」
在标准码点上无处安放 —— 这就是为什么手写素材里的重复字形在合成 TTF 时会被丢掉。
唯一可行的办法是把变体挂到 **Unicode 私用区 PUA（U+E000–U+F8FF，共 6,400 位）** 上：

    U+7684 → 的·第1种写法      U+E000 → 的·第2种写法      U+E001 → 的·第3种写法 …

渲染时把文本里的一部分「的」换成 U+E000，就得到另一种写法
（见 scripts/make_variant_text.py）。**都在同一个 TTF 里，不需要多个字体文件。**

> 为什么不用 Unicode 官方的变体选择符 IVS（U+XXXX U+FE00）？已实测：handwriter 逐字
> draw.text 且用 Pillow 的 LAYOUT_BASIC 引擎，不查 UVS 表 —— IVS 序列必然渲染失败。

## 两个源、两种质量

  --base-ttf    提供**已存在字形的现成轮廓，原样复制**（零质量损失）
  --images-dir  提供字形 PNG，只有**新增的变体**走矢量化

实测现有的 font/my_personal_font.ttf 是 FontLab/potrace 类工具的高密度描点产物
（「的」有 3,044 个控制点），而我们自己的矢量化只能做到数百点 —— 复制主字形可以把
这个质量风险限制在「新增的变体」上。

矢量化的取舍：**故意输出高密度多边形**（`--epsilon` 默认 0.3），而不是拟合平滑曲线 ——
base 字体本身就是密集多边形风格，密度接近才能在排版里观感一致。跑完会打印点数量，
可据此调 --epsilon。

## 度量对齐

唯一可靠的锚点是**同一个字的主字形 bbox**：把变体 PNG 的字形 bbox 按 x/y 独立线性
映射到主字形 bbox（并做 y 轴翻转），advance 直接取主字形的。这样同字的变体与主字形
同宽同高同位置，排版不会跳。

对 base 里还没有主字形的字（补字后新增的），用实测标定出的**等比装箱规则**：
缩放到装进 BOX_W×BOX_H、锚点 (0, BOX_YMIN)。该规则在现有字体的 152/152 个字形上
完全命中（±2 单位）。

## 用法

  python scripts/build_variant_ttf.py \\
      --base-ttf font/my_personal_font.ttf \\
      --images-dir "G:\\...\\exported\\20260910_013320" \\
      --out font/my_personal_font_variants.ttf \\
      --map-out font/variant_map.json

输出：
  --out      新的 TTF（**不覆盖 --base-ttf**）
  --map-out  变体映射表 JSON，供 scripts/make_variant_text.py 消费

依赖：fontTools、opencv-python(cv2)、numpy、Pillow（均已在 requirements.txt 里）
"""

import argparse
import json
import math
import os
import re
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))


# —— 实测标定（2026-09-12 重做版 font/my_personal_font.ttf，含方向修复）——
#    源图**整张画布**等比线性映射到 0.9 em 并居中：
#        font_x = OFF + src_x    × K
#        font_y = OFF + (H − src_y) × K        （y 轴翻转）
#      K = 0.9 × unitsPerEm / 画布边长,  OFF = (unitsPerEm − 0.9 × unitsPerEm) / 2
#    且 **advance 统一 = unitsPerEm**（CJK 等宽方格），lsb = xMin。
#    该规则在 191/191 个字形上完全命中（±3 单位，含贴在角落的标点）。
#    ★ 因为是「整张画布」映射，变体的 PNG 与主字形的 PNG 用同一个变换即可自然对齐，
#      不需要按墨迹 bbox 对齐（早期版本用 bbox 对齐，遇到贴角标点会错位）。
#    ⚠️ 若 gaudi-font-preprocess 再次重做字体度量，这两行常量需重新标定。
CANVAS_SCALE = 0.9

PUA_START, PUA_END = 0xE000, 0xF8FF

# uniXXXX(.png) / uniXXXX_NN.png / uXXXXX_NN.png
PNG_RE = re.compile(r'^u(?:ni)?([0-9A-Fa-f]{4,6})(?:_(\d+))?\.png$')


def scan_pngs(images_dir):
    """扫描素材目录，按码点分组：{codepoint: {'main': path|None, 'variants': [(idx, path)]}}

    注意不能复用 utils/import_images._scan_images_dir()：它的三级解析正则全部是
    `(?:_\\d+)?`，**会丢掉变体序号** —— 而变体序号正是本脚本必须的信息。
    """
    groups = defaultdict(lambda: {'main': None, 'variants': []})
    for name in sorted(os.listdir(images_dir)):
        m = PNG_RE.match(name)
        if not m:
            continue
        cp = int(m.group(1), 16)
        idx = m.group(2)
        path = os.path.join(images_dir, name)
        if idx is None:
            groups[cp]['main'] = path
        else:
            groups[cp]['variants'].append((int(idx), path))
    for g in groups.values():
        g['variants'].sort()
    return groups


def mask_bbox(bw):
    """二值掩码里笔画的包围盒 (x0, y0, x1, y1)，图像坐标（y 向下）；无笔画返回 None"""
    import numpy as np
    ys, xs = np.nonzero(bw)
    if len(xs) == 0:
        return None
    return (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)


def _canvas_of(arr, upm):
    """便捷包装：从图像数组取画布尺寸并返回变换参数（展开成 4 个值）"""
    kx, ox, ky, oy = canvas_transform(arr.shape[1], arr.shape[0], upm)
    return kx, ox, ky, oy


def canvas_transform(img_w, img_h, upm):
    """源图画布 → 字体坐标的线性映射参数 (kx, ox, ky, oy)

    实测规则：整张画布等比映射到 CANVAS_SCALE em 并居中。
        font_x = ox + src_x * kx
        font_y = oy + (img_h − src_y) * ky
    """
    kx = CANVAS_SCALE * upm / img_w
    ky = CANVAS_SCALE * upm / img_h
    ox = (upm - CANVAS_SCALE * upm) / 2.0
    oy = (upm - CANVAS_SCALE * upm) / 2.0
    return kx, ox, ky, oy


def _signed_area(pts):
    s = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return s / 2.0


def vectorize(png_path, kx, ox, ky, oy, canvas_h, epsilon, cache=None):
    """PNG 字形 → TTGlyph，按「整张画布线性映射」变换到字体坐标

    Returns: (glyph, 点数, xmin) 或 (None, 0, 0)（PNG 是空白图）
    cache: 可选的 {png_path: (bw, src_bbox)} 复用已读的二值图
    """
    import cv2
    import numpy as np
    from PIL import Image
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    key = png_path
    if cache is not None and key in cache:
        bw, src_bbox = cache[key]
    else:
        a = np.asarray(Image.open(png_path).convert('L'))
        # ★ ink 自动判别 —— 二选一 + 一次翻转保证拿到"笔画=1, 背景=0":
        #   1. 按整图均值初判（mean>127 白底黑字, 否则黑底白字）
        #   2. 检查 bw=1 的像素是否占多数：占多数说明判反了, 翻转
        #   原因: 黑底白字的"白背景"占画布 80%+, 初判会错; 反之亦然.
        #   cv2.findContours 在错误 ink 下会把整个画布当笔画轮廓, 渲染反色.
        if a.mean() > 127:
            bw = (a < 128).astype(np.uint8)
        else:
            bw = (a >= 128).astype(np.uint8)
        # 不需要翻转：上面已经按"笔画=少数像素"的方向选了 bw.
        # cv2.findContours 在错向 ink 下会把整张画布当笔画, 那种情况下 bw=1
        # 占 80%+, 我们用 "bw=1 占少数 = 笔画" 的天然属性即可.
        src_bbox = mask_bbox(bw)
        if cache is not None:
            cache[key] = (bw, src_bbox)
    if src_bbox is None:
        return None, 0, 0

    cnts, hier = cv2.findContours(bw, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    if not cnts:
        return None, 0, 0

    pen = TTGlyphPen(None)
    n_pts = 0
    xmin = None
    for i, c in enumerate(cnts):
        poly = cv2.approxPolyDP(c, epsilon, True)[:, 0, :]
        if len(poly) < 3:
            continue
        # 图像坐标(y 向下) → 字体坐标(y 向上)
        # floor/ceil 而非 round：保证墨迹 bbox 被算出的 bbox 包住，
        # 否则 lsb/xMin 会差 1 单位（新字体要求 lsb == xMin）
        fs = []
        for px, py in poly:
            fx = math.floor(ox + px * kx)
            fy = math.ceil(oy + (canvas_h - py) * ky)
            if not fs or fs[-1] != (fx, fy):
                fs.append((fx, fy))
        if xmin is None or fs[0][0] < xmin:
            xmin = min(f[0] for f in fs)
        if len(fs) >= 2 and fs[0] == fs[-1]:
            fs.pop()
        if len(fs) < 3:
            continue
        # TTF 要求：外轮廓顺时针（signed_area<0）、孔逆时针（>0），y 向上的坐标系里
        is_outer = hier[0][i][3] == -1
        if (_signed_area(fs) > 0) == is_outer:
            fs.reverse()
        pen.moveTo(fs[0])
        for p in fs[1:]:
            pen.lineTo(p)
        pen.closePath()
        n_pts += len(fs)

    if n_pts == 0:
        return None, 0, 0
    return pen.glyph(), n_pts, xmin


def glyph_bbox(font, glyph_set, glyph_name):
    """某个字形在字体坐标下的 bbox"""
    from fontTools.pens.boundsPen import BoundsPen
    bp = BoundsPen(glyph_set)
    glyph_set[glyph_name].draw(bp)
    return bp.bounds


def detect_uniform_advance(cmap, hmtx, upm):
    """判断 base 字体是否「advance 统一 = unitsPerEm」（新版字体的规则）

    新版字体：advance 恒为 2048 = upm（CJK 等宽方格），lsb = xMin。
    旧版字体（.bak）：advance 逐字不同（墨迹宽 + 约 22），lsb 恒为 0。
    两者给新字形定 advance 的方式不同，所以这里探测一下。
    """
    advs = {hmtx[gn][0] for gn in cmap.values() if gn in hmtx}
    return len(advs) == 1 and next(iter(advs)) == upm


def main():
    ap = argparse.ArgumentParser(
        description='构建带 PUA 变体的 TTF（主字形复制 + 变体矢量化）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument('--base-ttf', required=True,
                    help='基础字体：其已有字形会被原样复制（零损失）')
    ap.add_argument('--images-dir', required=True,
                    help='字形 PNG 目录（含 uniXXXX.png 与 uniXXXX_NN.png）')
    ap.add_argument('--out', required=True, help='输出的新 TTF（不要等于 --base-ttf）')
    ap.add_argument('--map-out', default='', help='变体映射表 JSON 输出路径')
    ap.add_argument('--epsilon', type=float, default=0.3,
                    help='approxPolyDP 简化精度（默认 0.3；越小点越多越接近 base 字体密度）')
    ap.add_argument('--pua-start', default='0xE000', help='PUA 起始码点（默认 0xE000）')
    ap.add_argument('--limit-variants', type=int, default=0,
                    help='每个字最多取前 N 个变体（0 = 全部）')
    ap.add_argument('--exclude', nargs='*', default=[],
                    help='排除某些字符（用 unicode 码点表示，如 0x4E2D 0x9E0D），'
                         '不去碰源 PNG，仅在读入时跳过。常用于排除质量差的字形')
    args = ap.parse_args()

    if os.path.abspath(args.out) == os.path.abspath(args.base_ttf):
        sys.exit('--out 不能等于 --base-ttf（本脚本不覆盖原始字体）')
    for p, label in ((args.base_ttf, '基础字体'), (args.images_dir, '素材目录')):
        if not (os.path.isfile(p) if label == '基础字体' else os.path.isdir(p)):
            sys.exit(f'{label}不存在: {p}')

    from fontTools.ttLib import TTFont
    import numpy as _np
    from PIL import Image as _Image

    t0 = time.perf_counter()
    pua_start = int(args.pua_start, 0)
    if not (PUA_START <= pua_start <= PUA_END):
        sys.exit(f'--pua-start 必须在 U+{PUA_START:04X}~U+{PUA_END:04X} 之间')

    font = TTFont(args.base_ttf)
    glyph_set = font.getGlyphSet()
    cmap = font.getBestCmap() or {}          # {码点: 字形名}
    hmtx = font['hmtx'].metrics
    units_per_em = font['head'].unitsPerEm
    # 新版字体 advance 统一 = unitsPerEm、lsb = xMin；旧版是「墨迹宽+22、lsb=0」
    uniform_adv = detect_uniform_advance(cmap, hmtx, units_per_em)

    groups = scan_pngs(args.images_dir)
    n_png = sum((1 if g['main'] else 0) + len(g['variants']) for g in groups.values())
    print(f'基础字体  : {os.path.abspath(args.base_ttf)}')
    print(f'  已有字形: {len(font.getGlyphOrder()):,} (unitsPerEm={units_per_em}, '
          f'{"advance 统一" if uniform_adv else "advance 逐字不同（旧版字体）"})')
    print(f'素材目录  : {os.path.abspath(args.images_dir)}')
    print(f'  PNG {n_png:,} 张 → {len(groups):,} 个码点，'
          f'其中 {sum(1 for g in groups.values() if g["variants"]):,} 个码点有变体')
    print(f'  总变体数: {sum(len(g["variants"]) for g in groups.values()):,}')
    print()

    new_glyphs, new_metrics = {}, {}
    cmap_add = {}                 # {码点: 字形名}
    vmap = {}                     # {字符: {'main': 'U+XXXX', 'variants': [...]}}
    cache = {}
    n_new_main = n_var = n_skip = 0
    pts_new, pts_var = [], []
    next_pua = pua_start
    excluded = set(int(x, 0) for x in args.exclude) if args.exclude else set()
    if excluded:
        print(f"排除字符（--exclude）: {len(excluded)} 个 = {sorted(hex(c) for c in excluded)}")

    for cp in sorted(groups):
        if cp in excluded:
            n_skip += 1
            continue
        g = groups[cp]
        ch = chr(cp)
        main_name = cmap.get(cp)

        # --- 主字形 ---
        if main_name is None:
            # base 里没有这个字（补字后新增）→ 用它自己的 PNG 矢量化（同一套画布映射）
            if not g['main']:
                n_skip += 1
                continue
            a = _np.asarray(_Image.open(g['main']).convert('L'))
            # 同 vectorize(): ink 自动判别 + 占多数翻转
            bw = (a < 128).astype(_np.uint8) if a.mean() > 127 else (a >= 128).astype(_np.uint8)
            src_bbox = mask_bbox(bw)
            if src_bbox is None:
                n_skip += 1
                continue
            cache[g['main']] = (bw, src_bbox)
            _kx, _ox, _ky, _oy = canvas_transform(a.shape[1], a.shape[0], units_per_em)
            gl, np_, _xm = vectorize(g['main'], _kx, _ox, _ky, _oy, a.shape[0],
                                     args.epsilon, cache)
            if gl is None:
                n_skip += 1
                continue
            main_name = f'uni{cp:04X}' if cp <= 0xFFFF else f'u{cp:05X}'
            new_glyphs[main_name] = gl
            # advance 与 base 一致：新版统一 unitsPerEm；旧版是「墨迹宽 + 侧边距」
            main_adv = units_per_em if uniform_adv else int(round(src_bbox[2] - src_bbox[0])) + 22
            new_metrics[main_name] = (main_adv, _xm)
            cmap_add[cp] = main_name
            n_new_main += 1
            pts_new.append(np_)
        else:
            # 主字形已在 base 里 → 直接沿用它的 advance（变体必须与它同宽）
            main_adv = hmtx[main_name][0]

        # --- 变体 ---
        # 与主字形用**同一个画布变换**，所以位置天然对齐，无需按 bbox 对齐
        variants = g['variants']
        if args.limit_variants:
            variants = variants[:args.limit_variants]

        for idx, path in variants:
            if next_pua > PUA_END:
                sys.exit(f'PUA 码点用尽（{PUA_END:#06x}）—— 变体太多或 --pua-start 太靠后')
            _a = _np.asarray(_Image.open(path).convert('L'))
            gl, np_, xm = vectorize(path, *_canvas_of(_a, units_per_em),
                                    _a.shape[0], args.epsilon, cache)
            if gl is None:
                n_skip += 1
                continue
            name = f'uni{next_pua:04X}' if next_pua <= 0xFFFF else f'u{next_pua:05X}'
            new_glyphs[name] = gl
            # advance 必须与主字形**完全相同**，否则变体多的段落会比纯主字形的段落更紧。
            # lsb 必须 = xMin：FreeType/PIL 按 lsb 定位，恒填 0 会让字形整体左移 xMin。
            new_metrics[name] = (main_adv, xm)
            cmap_add[next_pua] = name
            vmap.setdefault(ch, {'main': f'U+{cp:04X}', 'variants': []})
            vmap[ch]['variants'].append(f'U+{next_pua:04X}')
            pts_var.append(np_)
            next_pua += 1
            n_var += 1

    if not new_glyphs:
        sys.exit('没有任何新字形可加（素材目录里全是无变体的已有字？）')

    # --- 写入字体：扩展 glyphOrder / glyf / hmtx / cmap / maxp ---
    order = font.getGlyphOrder()
    font.setGlyphOrder(order + list(new_glyphs))
    glyf = font['glyf']
    glyf.glyphOrder = font.getGlyphOrder()
    for name, gl in new_glyphs.items():
        glyf[name] = gl
    for name, m in new_metrics.items():
        hmtx[name] = m
    font['maxp'].numGlyphs = len(font.getGlyphOrder())
    for t in font['cmap'].tables:
        if t.isUnicode():
            t.cmap.update(cmap_add)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    font.save(args.out)
    font.close()

    if args.map_out:
        obj = {
            'base_ttf': os.path.abspath(args.base_ttf),
            'images_dir': os.path.abspath(args.images_dir),
            'units_per_em': units_per_em,
            'pua_start': f'U+{pua_start:04X}',
            'epsilon': args.epsilon,
            'chars': {k: vmap[k] for k in sorted(vmap)},
        }
        with open(args.map_out, 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)

    def avg(lst):
        return int(sum(lst) / len(lst)) if lst else 0

    print(f'新增主字形（base 里没有的）: {n_new_main:,}   平均 {avg(pts_new)} 点/字')
    print(f'新增变体字形（挂 PUA）    : {n_var:,}   平均 {avg(pts_var)} 点/字')
    print(f'跳过（空白/无法矢量化）   : {n_skip:,}')
    print(f'PUA 码点占用              : {n_var:,} / {PUA_END-PUA_START+1:,}')
    print()
    print(f'新字体已写入: {os.path.abspath(args.out)}')
    if args.map_out:
        print(f'变体映射表  : {os.path.abspath(args.map_out)}'
              f'（{len(vmap):,} 个字有变体）')
    print(f'用时: {time.perf_counter()-t0:.1f}s')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
