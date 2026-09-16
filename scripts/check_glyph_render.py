# -*- coding: utf-8 -*-
"""字形栅格化体检 —— 扫字体每个 char, PIL getmask 检测渲染异常

用途: 之前用 `ink > 0` 当通过门槛, 但细笔画字符 (如 @ # 看 一)
会被 build_personal_ttf.py 的列扫描矩形算法产出 1-像素宽矩形,
96pt 渲染时矩形亚像素, 抗锯齿吃掉 → ink=63/76 但视觉上是散点.

2026-09-16 dev 那边改了 PROBE_SIZE=64, threshold=50.
本脚本同步升级: 阈值改为 50, 与 dev 的 fallback 阈值对齐, 拦住散点陷阱.

用法:
  python scripts/check_glyph_render.py font/my_personal_font.ttf
  python scripts/check_glyph_render.py font/my_personal_font_variants.ttf
  python scripts/check_glyph_render.py font/my_personal_font.ttf --size 96
  python scripts/check_glyph_render.py font/my_personal_font.ttf --threshold 100
  python scripts/check_glyph_render.py font/my_personal_font.ttf --output failed.txt

返回:
  exit 0 = 全部能渲染
  exit 1 = 有失败 (让 CI/构建能 fail-fast)
"""
import argparse
import sys
import os

import numpy as np
from PIL import Image, ImageFont


def main():
    ap = argparse.ArgumentParser(description='扫字体每个字形, 检测渲染异常 (ink 太低=散点/空白)')
    ap.add_argument('ttf', help='TTF 路径')
    ap.add_argument('--size', type=int, default=64, help='PIL 渲染字号 (默认 64)')
    ap.add_argument('--threshold', type=int, default=50,
                    help='判定异常的 ink 下限 (默认 50, 与 dev fallback 阈值对齐)')
    ap.add_argument('--output', default='', help='失败清单输出路径 (默认打印到 stdout)')
    ap.add_argument('--exclude', nargs='*', default=[],
                    help='排除某些字符的码点 (十进制 0x 前缀可), 如 0x4E2D 0x9E0D')
    args = ap.parse_args()

    if not os.path.isfile(args.ttf):
        sys.exit(f'文件不存在: {args.ttf}')

    from fontTools.ttLib import TTFont
    tt = TTFont(args.ttf)
    cm = tt.getBestCmap() or {}
    tt.close()

    f = ImageFont.truetype(args.ttf, args.size)
    excluded = set()
    for x in args.exclude:
        if x.startswith(('0x', '0X')):
            excluded.add(int(x, 16))
        else:
            excluded.add(int(x))

    rows = []
    for cp, gn in sorted(cm.items()):
        if cp in excluded:
            continue
        ch = chr(cp)
        try:
            a = np.asarray(f.getmask(ch))
            ink = int((a > 0).sum())
        except Exception as e:
            ink = -1
        if ink < args.threshold:
            rows.append((cp, ch, gn, ink))

    head = f'=== {os.path.basename(args.ttf)} @ {args.size}px (threshold={args.threshold}) ===\n'
    head += f'字符数: {len(cm)}, 失败: {len(rows)}, 排除: {len(excluded)}\n'
    print(head, end='')
    if not rows:
        print('✅ 全部字形能正常渲染')
        return 0

    print('失败的字形 (码点 / 字 / glyph名 / ink):')
    lines = []
    for cp, ch, gn, ink in rows:
        line = f'  U+{cp:04X}  {ch!r:<6}  {gn:<14}  ink={ink}'
        print(line)
        lines.append(line)

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(head + '\n'.join(lines) + '\n')
        print(f'\n已写入: {args.output}')

    return 1


if __name__ == '__main__':
    sys.exit(main())
