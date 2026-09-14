#!/usr/bin/env python3
"""
从「导出训练包」的字形图合成一个 TTF 字体。

★ 本脚本拷贝自同作者（UryWu）的姊妹项目 gaudi-font-preprocess
   源: G:\Projects\projects_ai\gaudi-font-preprocess\scripts\build_personal_ttf.py
   拷入日期: 2026-09-14

为何拷贝：本项目 (gaudi-ai-font-tool) 训练流程需要 REF_FONT,
   而 gaudi-font-preprocess 的 build_personal_ttf.py 是唯一能在新数据
   (data/sessions/all_characters/) 上重生 .ttf 的工具.
   之前只能让 preprocess-dev 那边跑, 跨项目协作慢一拍; 现在直接放本项目里即可.

包装变更: 把默认路径指向本项目的训练素材与字体路径, 调用更顺手:
  默认 --export-dir  → data/sessions/all_characters (若存在) 否则报错
  默认 --out          → font/my_personal_font.ttf
其余功能 / 算法 / 度量与源完全一致, 见原文件 docstring.

用法 (在本项目根目录):

  python scripts/build_personal_ttf.py --out font/my_personal_font.ttf
  python scripts/build_personal_ttf.py \
      --export-dir "<preprocess 项目的合并目录>" --out font/my_personal_font.ttf

依赖 (本项目 requirements.txt 都有):
  fontTools + Pillow + numpy
"""
# ↑ 以上为本项目包装的注释, 下文为原始代码 (除默认路径已改外, 未做任何修改)

import argparse
import os
import re
import sys

from PIL import Image
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

# 导出训练包里的字形图尺寸（见 /annotate 的「导出训练包」）
PNG_SIZE = 512

# 会话布局：data/sessions/<hash>/exported/<时间戳>/
# 时间戳目录名规则与 app.py 的 _scan_session_exports() 保持一致
TS_PATTERN = re.compile(r"^\d{8}_\d{6}$")

# 导出文件名：uniXXXX.png（BMP）或 uXXXXX.png（扩展区），可能带 _01/_02 去重后缀
NAME_PATTERN = re.compile(r"^(uni([0-9A-F]{4})|u([0-9A-F]{5}))(?:_\d+)?\.png$")


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="从导出的字形图合成 TTF 字体（拷自 gaudi-font-preprocess）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="提示：不知道导出目录在哪时，用 --session 指定会话 hash 即可自动找最近一次导出。",
    )

    src = p.add_argument_group("输入")
    # ★ 默认值改为本项目训练素材路径
    src.add_argument("--export-dir",
                     default=r"G:\Projects\projects_ai\gaudi-font-preprocess\data\sessions\all_characters",
                     help="导出训练包目录（含 uniXXXX.png / uXXXXX.png）"
                          "（默认 = preprocess 项目的合并目录 all_characters/）")
    src.add_argument("--session", help="会话 hash；与 --export-dir 二选一，自动取该会话的导出目录")
    src.add_argument("--export-version",
                     help="配合 --session 指定具体导出批次（时间戳目录名）；默认取最新的一次")
    src.add_argument("--data-dir", default=None,
                     help="会话数据根目录，默认 <项目根>/data/sessions")

    out = p.add_argument_group("输出")
    # ★ 默认值改为本项目字体路径
    out.add_argument("--out",
                     default=r"G:\Projects\projects_ai\gaudi-ai-font-tool\font\my_personal_font.ttf",
                     help="输出的 .ttf 路径（默认 = 本项目 font/my_personal_font.ttf）")

    font = p.add_argument_group("字体信息")
    font.add_argument("--family", default="我的书法", help="familyName（默认 我的书法）")
    font.add_argument("--style", default="Regular", help="styleName（默认 Regular）")
    font.add_argument("--ps-name", default="MyCalligraphy-Regular", help="PostScript 名")
    font.add_argument("--font-version", default="1.0",
                      help="字体版本号（写进 name 表）")
    font.add_argument("--copyright", default="Copyright UryWu")

    metric_args = p.add_argument_group("度量")
    metric_args.add_argument("--upm", type=int, default=2048,
                             help="unitsPerEm（默认 2048，与 ai-font-tool 的 default.ttf 一致）")
    metric_args.add_argument("--ascent", type=int, default=1638)
    metric_args.add_argument("--descent", type=int, default=-409)
    metric_args.add_argument("--canvas-ratio", type=float, default=0.9,
                             help="512 画布换算到 em 的比例（默认 0.9 → 缩放系数 1843/512）。"
                                  "整张画布线性映射到 em 框（画布水平居中、底边距 baseline 为 em 的 5%），"
                                  "所以字形在画布里的位置会被保留——贴角放置的标点仍是贴角")
    metric_args.add_argument("--baseline-pad-ratio", type=float, default=0.05,
                             help="字形底边与 baseline 的距离占 em 的比例（默认 0.05）")

    ink = p.add_argument_group("图像")
    ink.add_argument("--ink", choices=("auto", "dark", "bright"), default="auto",
                     help="哪一侧是笔画：dark=白底黑字（导出包的默认形态）、"
                          "bright=黑底白字；auto 按整图明暗自动判断")

    return p.parse_args(argv)


def resolve_export_dir(args):
    """把 --export-dir / --session 解析成一个确定的导出目录"""
    if args.export_dir:
        d = os.path.abspath(args.export_dir)
        if not os.path.isdir(d):
            sys.exit(f"错误：导出目录不存在 → {d}")
        return d

    if not args.session:
        sys.exit("错误：需要 --export-dir 或 --session 指定输入（-h 看用法）")

    data_dir = args.data_dir or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "sessions")
    exported = os.path.join(data_dir, args.session, "exported")
    if not os.path.isdir(exported):
        sys.exit(f"错误：该会话没有导出目录 → {exported}")

    # 只认时间戳命名的子目录（与 app.py 的 _scan_session_exports 同一规则，
    # 这样 backup/ 之类的手工目录不会被误当成一次导出）
    ts_dirs = [d for d in os.listdir(exported)
               if TS_PATTERN.match(d) and os.path.isdir(os.path.join(exported, d))]
    if not ts_dirs:
        sys.exit(f"错误：导出目录下没有时间戳批次 → {exported}")

    if args.export_version:
        if args.export_version not in ts_dirs:
            sys.exit(f"错误：没有这一批导出 → {args.export_version}"
                     f"（现有：{', '.join(sorted(ts_dirs))}）")
        chosen = args.export_version
    else:
        # 默认取最新的一批（时间戳目录名可直接字符串比较，格式固定 YYYYMMDD_HHMMSS）
        chosen = sorted(ts_dirs)[-1]

    print(f"导出批次：{chosen}（{'指定' if args.export_version else '最新'}）")
    return os.path.join(exported, chosen)


def collect_entries(export_dir):
    """
    扫描导出目录，返回 [(码点, 图片路径)]，同码点只保留第一张。

    排序后遍历，保证 `uni7684.png` 排在 `uni7684_01.png` 之前 —— 也就是取
    「无后缀那张」（同字多样本里的第一张）。
    """
    seen = set()
    entries = []
    for fn in sorted(os.listdir(export_dir)):
        m = NAME_PATTERN.match(fn)
        if not m:
            continue
        # uniXXXX → BMP 区直接就是码点；uXXXXX → 扩展区，需 +0x10000
        cp = int(m.group(2), 16) if m.group(2) else int(m.group(3), 16) + 0x10000
        if cp in seen:
            continue
        seen.add(cp)
        entries.append((cp, os.path.join(export_dir, fn)))
    entries.sort()
    return entries


def glyph_name(cp):
    """FontLab 命名规范：BMP 区 uniXXXX，扩展区 uXXXXX"""
    return f"uni{cp:04X}" if cp <= 0xFFFF else f"u{cp - 0x10000:05X}"


def load_ink_mask(png_path, ink_mode):
    """
    读图并返回「笔画 = True」的布尔矩阵。

    ink_mode：dark=白底黑字（导出包默认形态，笔画是暗的）、bright=黑底白字。
    auto 时按整图平均明暗判断——导出包是白底黑字（均值偏亮），而 /scale 的
    中间产物是黑底白字（均值偏暗），两种都常见，自动判能少踩一次坑。
    """
    img = Image.open(png_path).convert("L")
    if img.size != (PNG_SIZE, PNG_SIZE):
        img = img.resize((PNG_SIZE, PNG_SIZE))

    if ink_mode == "auto":
        # 取均值即可：白底黑字整图偏亮，黑底白字偏暗。阈值 127 对两种情况都够稳
        avg = sum(img.getdata()) / float(PNG_SIZE * PNG_SIZE)
        ink_mode = "dark" if avg > 127 else "bright"

    # 用 256 项查找表做二值化（point 传 LUT 是 C 层实现，比传 lambda 快很多）
    if ink_mode == "dark":          # 白底黑字：暗的是笔画
        lut = [1] * 129 + [0] * 127
    else:                           # 黑底白字：亮的是笔画
        lut = [0] * 128 + [1] * 128
    return img.point(lut)


def build_glyph(mask, upm, canvas_units, baseline_pad):
    """
    把笔画掩码转成一个 TrueType 字形。

    做法：按列扫描，每列里每段连续笔画生成一个 4 点闭合矩形。不用 potrace
    这类描边工具，代价是轮廓呈阶梯状（这是刻意保留手写笔触瑕疵的取舍，见模块 docstring）。

    映射方式：**整张画布线性映射到 em**（不是按墨迹包围盒对齐）。
      - 水平：画布居中于 em 框，画布坐标直接乘以缩放系数
      - 垂直：画布底边落在 baseline 之上 baseline_pad 处，y 轴方向翻转
    这样字形在画布里的位置会被保留 —— 贴角放置的标点（见 /annotate 的角对齐）
    到字体里仍贴角，不会被挪到中间。

    坐标系：图片左上角为原点、y 向下（0 = 画布顶）；字形坐标 y 向上、baseline 为 0。

    注意：早期版本按「墨迹包围盒」对齐（墨迹居中于 em），而且 y 映射写反了
    （把图里靠上的行映射到字形里更低的位置）—— 结果是字形上下**翻转**。
    两处都已修，若再改这段务必核对方向。
    """
    px = mask.load()
    size = PNG_SIZE
    scale = canvas_units / float(size)

    # 画布水平居中于 em 框（画布宽 = size*scale，两侧各留这么多）
    x_pad = (upm - size * scale) / 2.0

    # 墨迹包围盒只用来判断「这张图是不是空白」，不再参与定位
    has_ink = False
    for x in range(size):
        for y in range(size):
            if px[x, y]:
                has_ink = True
                break
        if has_ink:
            break
    if not has_ink:
        return None   # 整图无笔画

    pen = TTGlyphPen(None)
    for x in range(size):
        y = 0
        while y < size:
            while y < size and px[x, y] == 0:
                y += 1
            y_start = y
            while y < size and px[x, y] == 1:
                y += 1
            if y > y_start:
                x_left = x * scale + x_pad
                x_right = x_left + scale
                # 图片 y 向下（0=画布顶）→ 字形 y 向上（0=baseline）：
                # 画布最下一行落在 baseline_pad 处，越靠上的行字形 y 越大。
                # 一行像素占 [y_i, y_i+1) 的图像区间，映射后：
                #   该行下边缘 → baseline_pad + (size - y_i - 1) * scale
                # 于是整段（上边缘行 y_start、下边缘行 y-1）是：
                y_bottom = baseline_pad + (size - y) * scale
                y_top = baseline_pad + (size - y_start) * scale
                pen.moveTo((x_left, y_bottom))
                pen.lineTo((x_right, y_bottom))
                pen.lineTo((x_right, y_top))
                pen.lineTo((x_left, y_top))
                pen.closePath()

    return pen.glyph()


def main(argv=None):
    args = parse_args(argv)

    export_dir = resolve_export_dir(args)
    entries = collect_entries(export_dir)
    if not entries:
        sys.exit(f"错误：目录里没找到 uniXXXX.png / uXXXXX.png → {export_dir}")
    print(f"输入目录：{export_dir}")
    print(f"唯一字符数：{len(entries)}")

    upm = args.upm
    canvas_units = int(upm * args.canvas_ratio)
    baseline_pad = int(upm * args.baseline_pad_ratio)

    # .notdef 必须有：字形 0 号、cmap 的 0 也指向它
    glyph_order = [".notdef"]
    glyphs = {".notdef": TTGlyphPen(None).glyph()}
    cmap = {0: ".notdef"}

    skipped = []
    for cp, path in entries:
        name = glyph_name(cp)
        mask = load_ink_mask(path, args.ink)
        glyph = build_glyph(mask, upm, canvas_units, baseline_pad)
        if glyph is None:
            skipped.append(os.path.basename(path))
            continue
        glyphs[name] = glyph
        glyph_order.append(name)
        cmap[cp] = name

    if skipped:
        print(f"跳过 {len(skipped)} 张空白图：{', '.join(skipped[:5])}"
              + (" …" if len(skipped) > 5 else ""))
    if len(glyphs) <= 1:
        sys.exit("错误：所有图都是空白，没生成任何字形")

    print(f"生成字形：{len(glyphs) - 1} 个（+ .notdef）")

    # === 建字体 ===
    fb = FontBuilder(upm, isTTF=True)
    fb.setupGlyphOrder(glyph_order)
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(glyphs)    # 这一步会算好每个字形的包围盒（xMin/xMax/yMin/yMax）

    # hmtx：advance 统一取整个 em 框（CJK 字体每字占一个等宽方格，字形已落在 em 框内，
    # 不会溢出步进框）；**lsb 必须等于该字形的 xMin**（TrueType 惯例）。
    # 把 lsb 写成 0 会让 FreeType/PIL 这类渲染器按 lsb 定位，字形整体左移 xMin ——
    # 实测：lsb=0 时 PIL 渲染的墨迹左边界恒等于笔位（本例偏了 37~125px），
    # 而 lsb==xMin 的 default.ttf 墨迹正好落在 xMin 处。
    metrics = {}
    for name in glyph_order:
        g = glyphs[name]
        metrics[name] = (upm, getattr(g, "xMin", 0) or 0)
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=args.ascent, descent=args.descent)
    fb.setupNameTable({
        "familyName": args.family,
        "styleName": args.style,
        "psName": args.ps_name,
        "fullName": f"{args.family} {args.style}",
        "version": args.font_version,
        "copyright": args.copyright,
    })
    fb.setupOS2(
        sTypoAscender=args.ascent,
        sTypoDescender=args.descent,
        usWinAscent=args.ascent,
        usWinDescent=abs(args.descent),
    )
    # keepGlyphNames 默认 True → post 写 format 2.0，保留 uniXXXX 字形名。
    # 若写成 format 3.0，字体里就只剩 glyph00001 这类编号名了
    fb.setupPost()
    fb.setupMaxp()

    out_path = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    fb.save(out_path)
    print(f"已写出：{out_path}（{os.path.getsize(out_path):,} bytes）")

    # === 回读校验：写完立刻用 fontTools 重新加载一遍，确认是合法字体 ===
    verify(out_path)
    return 0


def verify(ttf_path):
    """回读校验：字形数、cmap、命名、度量是否都符合预期"""
    from fontTools.ttLib import TTFont
    f = TTFont(ttf_path)
    order = f.getGlyphOrder()
    names_ok = all(n == ".notdef" or n.startswith(("uni", "u")) for n in order)
    # lsb 必须等于 xMin，否则渲染器（FreeType/PIL 等）会把字形整体左移，见 main 里的说明
    lsb_bad = [n for n in order
               if f["glyf"][n].numberOfContours > 0 and f["hmtx"][n][1] != f["glyf"][n].xMin]
    print("\n校验（重新加载该字体）：")
    print(f"  family / style : {f['name'].getBestFamilyName()} / {f['name'].getBestSubFamilyName()}")
    print(f"  unitsPerEm     : {f['head'].unitsPerEm}")
    print(f"  ascent/descent : {f['hhea'].ascent} / {f['hhea'].descent}")
    print(f"  字形数         : {len(order)}（含 .notdef）")
    print(f"  cmap 码点数    : {len(f['cmap'].tables[0].cmap)}")
    print(f"  字形名规范     : {'✓' if names_ok else '✗'}（前几个：{', '.join(order[:4])}）")
    print(f"  字宽           : {sorted({f['hmtx'][n][0] for n in order[1:]})}")
    print(f"  lsb == xMin    : {'✓' if not lsb_bad else '✗ 异常字形 ' + ', '.join(lsb_bad[:3])}")


if __name__ == "__main__":
    sys.exit(main())
