# -*- coding: utf-8 -*-
"""书写清单生成 —— 算出「该补写哪些字、每个字写几种」，输出一张 CSV

场景：要让一套个人字库盖住某篇文档，需要手写补字。本脚本回答两个问题：
  1. 补哪些字？（按文档字频降序 = 描写优先级；写不完也能保证覆盖最高的那批）
  2. 每个字写几种写法？（用于「同一篇文章里同字有不同写法」）

变体数按文档字频分档，比「一律 N 种」更省力、也更合理：

  出现次数 ≥ 800 → 8 种 | ≥ 300 → 6 | ≥ 100 → 5 | ≥ 30 → 4 | ≥ 10 → 3 | ≥ 3 → 2 | 其余 1
  （实测一篇 3.3 万字的稿：1,176 个缺失字 → 共写 2,517 个字形；
    一律 3 种则要 3,528 个，分档省 29%）
  想强制统一，用 --uniform N。

数字 0-9 特殊处理：**只要文档里出现过，就强制纳入清单，不受 --limit 截断**
（一共才 10 个字符、写起来快，但任何稿子里都离不开）。

★ 写的时候请**把同一个字的多种写法连着写**（同字相邻）。
  这样写完后拍照，gaudi-font-preprocess 的 OCR 会把连写的同一个字识别成同一字符，
  导出时自动变成 uniXXXX.png + uniXXXX_01.png… **天然就是变体序列**，
  不需要任何人工标注对应关系。

用法：
  python scripts/make_write_list.py --font font/my_personal_font.ttf \\
      --doc "F:\\Files\\入党\\入党积极分子思想汇报_3000字左右.md" --out 书写清单.csv

  # 先只写优先级最高的 300 个字
  python scripts/make_write_list.py --font ... --doc ... --limit 300 --out 清单_前300.csv

输出 CSV 列：
  priority            描写优先级（1 = 最先写）
  char / unicode      目标字 / 码点
  category            汉字 / 数字 / 中文标点
  count               该字在文档里出现的次数（= 分档依据）
  variants_to_write   建议写几种写法
  glyph_name          将来在字体里的字形名（uniXXXX）
  以 utf-8-sig 写出，Excel 双击不乱码

依赖：
  - scripts/char_freq.py（复用 read_text / classify / FONT_SCOPE，不重写）
  - utils/charset_utils.py（fontlab_filename）
  - fontTools（读字库原始 cmap）
"""

import argparse
import csv
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from char_freq import read_text, classify, FONT_SCOPE  # noqa: E402
from utils.charset_utils import fontlab_filename      # noqa: E402


# 字频 → 建议写法数（从高到低匹配，第一个命中的生效）
TIERS = ((800, 8), (300, 6), (100, 5), (30, 4), (10, 3), (3, 2), (0, 1))

DIGITS = set('0123456789')


def variants_for(count, uniform=0):
    """该字的文档出现次数 → 建议写几种写法"""
    if uniform > 0:
        return uniform
    for thresh, n in TIERS:
        if count >= thresh:
            return n
    return 1


def load_font_chars(ttf_path):
    """读字体的**原始 cmap**（全部码点 → 字符集）

    注意不能用 utils.charset_utils.get_font_chars()：那个按设计只返回「汉字」，
    内部用 is_cjk 过滤，而 CJK_RANGES 不含 。(U+3002) ，(U+FF0C) 等 CJK 标点，
    会把字库里明明有的高频标点误判成「缺失」。
    """
    from fontTools.ttLib import TTFont
    ft = TTFont(ttf_path)
    cmap = ft.getBestCmap() or {}
    ft.close()
    return {chr(cp) for cp in cmap}


def build_list(doc_path, font_chars, limit=0, uniform=0):
    """按文档字频降序算出待补字清单

    Returns: [(char, codepoint, category, count, variants), ...]
    """
    text, _enc = read_text(doc_path)
    freq = Counter(text)

    scope = [c for c in freq if classify(c) in FONT_SCOPE]
    scope.sort(key=lambda c: (-freq[c], ord(c)))
    missing = [c for c in scope if c not in font_chars]

    if limit > 0:
        head = missing[:limit]
        # 数字 0-9 强制纳入（见模块 docstring）
        tail = [c for c in missing[limit:] if c in DIGITS and c not in set(head)]
        missing = head + tail

    return [(c, ord(c), classify(c), freq[c], variants_for(freq[c], uniform))
            for c in missing]


def main():
    ap = argparse.ArgumentParser(
        description='书写清单生成（算出该补写哪些字、每个字写几种写法）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument('--font', required=True, help='当前字库 TTF（用它判断哪些字还缺）')
    ap.add_argument('--doc', required=True, help='目标文档（.md/.txt）')
    ap.add_argument('--out', required=True, help='书写清单 CSV 输出路径')
    ap.add_argument('--limit', type=int, default=0,
                    help='只取优先级最高的前 N 个字（0 = 全部；数字 0-9 不受此限制）')
    ap.add_argument('--uniform', type=int, default=0,
                    help='每个字强制写这么多种（0 = 用字频分档）')
    args = ap.parse_args()

    for p, label in ((args.font, '字库'), (args.doc, '文档')):
        if not os.path.isfile(p):
            sys.exit(f'{label}不存在: {p}')

    items = build_list(args.doc, load_font_chars(args.font),
                       args.limit, args.uniform)

    with open(args.out, 'w', encoding='utf-8-sig', newline='') as f:
        wr = csv.writer(f)
        wr.writerow(['priority', 'char', 'unicode', 'category', 'count',
                     'variants_to_write', 'glyph_name'])
        for i, (ch, cp, cat, cnt, n) in enumerate(items, 1):
            wr.writerow([i, ch, f'U+{cp:04X}', cat, cnt, n,
                         fontlab_filename(cp)[:-4]])

    total_glyphs = sum(n for *_x, n in items)
    print(f'字库      : {os.path.abspath(args.font)}')
    print(f'文档      : {os.path.abspath(args.doc)}')
    print(f'需补字    : {len(items):,} 个，共写 {total_glyphs:,} 个字形')
    if args.uniform:
        print(f'写法数    : 一律 {args.uniform} 种（--uniform）')
    else:
        dist = Counter(n for *_x, n in items)
        print('写法数分布: ' + '  '.join(f'{v}种×{dist[v]}字'
                                         for v in sorted(dist, reverse=True)))
    dig = [(c, n) for c, _cp, cat, _cnt, n in items if cat == '数字']
    if dig:
        print(f'数字 0-9  : ' + '  '.join(f'{c}×{n}种' for c, n in
                                          sorted(dig, key=lambda x: x[0])))
    print()
    print('优先级 1-20: ' + ''.join(c for c, *_x in items[:20]))
    print(f'\n书写清单已写入: {os.path.abspath(args.out)}')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
