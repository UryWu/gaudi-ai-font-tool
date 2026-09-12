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
  # 单篇
  python scripts/make_write_list.py --font font/my_personal_font.ttf \\
      --doc "F:\\Files\\入党\\xxx.md" --out 书写清单.csv

  # 多篇（字频合并累计）
  python scripts/make_write_list.py --font font/my_personal_font.ttf \\
      --doc 心得.md 申请书.md --out 书写清单_心得_申请书.csv

  # ★ 追加新文档时：先排除已排进历史清单的字（支持通配符）
  python scripts/make_write_list.py --font font/my_personal_font.ttf \\
      --doc 新文档.md --exclude-csv "书写清单*.csv" --out 书写清单_新文档.csv

  # 盘点已写字形（不从文档算，纯粹统计素材目录里写了什么）
  python scripts/make_write_list.py --images-dir "G:\\...\\exported\\<时间戳>" \\
      --out 已写清单.csv

  # 先只写优先级最高的 300 个字
  python scripts/make_write_list.py --font ... --doc ... --limit 300 --out 清单_前300.csv

输出 CSV 列（--doc 模式）：
  priority            描写优先级（1 = 最先写）
  char / unicode      目标字 / 码点
  category            汉字 / 数字 / 中文标点
  count               该字在文档里出现的次数（= 分档依据）
  variants_to_write   建议写几种写法
  glyph_name          将来在字体里的字形名（uniXXXX）
  以 utf-8-sig 写出，Excel 双击不乱码

输出 CSV 列（--images-dir 模式）：
  priority, char, unicode, category, png_count, variants_written, glyph_name, png_files

依赖：
  - scripts/char_freq.py（复用 read_text / classify / FONT_SCOPE，不重写）
  - utils/charset_utils.py（fontlab_filename）
  - fontTools（读字库原始 cmap）
"""

import argparse
import csv
import glob
import os
import re
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


def load_csv_chars(csv_path):
    """读一份书写清单 CSV，取出其中的 char 列（用于 --exclude-csv）

    只认表头里有 `char` 列的 CSV；读不出内容就返回空集（不报错，避免挡住主流程）。
    """
    charset = set()
    try:
        with open(csv_path, 'r', encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f):
                ch = (row.get('char') or '').strip()
                if len(ch) == 1:
                    charset.add(ch)
    except Exception as e:
        print(f'⚠️ 读取 --exclude-csv 失败（忽略）: {csv_path}: {e}')
    return charset


def build_list(doc_paths, font_chars, limit=0, uniform=0, exclude=None):
    """按文档字频降序算出待补字清单

    Args:
        doc_paths: 一到多篇文档；多篇时字频**合并累计**（同一字在多篇里的出现次数相加）
        font_chars: 字库已有字符（排除）
        exclude: 额外要排除的字符（如已排进其他书写清单的字）

    Returns: [(char, codepoint, category, count, variants), ...]
    """
    freq = Counter()
    for p in doc_paths:
        text, _enc = read_text(p)
        freq.update(text)          # 多篇合并计数（出现次数相加）

    skip = set(font_chars) | set(exclude or ())
    scope = [c for c in freq if classify(c) in FONT_SCOPE]
    scope.sort(key=lambda c: (-freq[c], ord(c)))
    missing = [c for c in scope if c not in skip]

    if limit > 0:
        head = missing[:limit]
        # 数字 0-9 强制纳入（见模块 docstring）
        tail = [c for c in missing[limit:] if c in DIGITS and c not in set(head)]
        missing = head + tail

    return [(c, ord(c), classify(c), freq[c], variants_for(freq[c], uniform))
            for c in missing]


def build_written_list(images_dir, uniform=0):
    """--images-dir 模式：统计**已经写好**的字形（从素材 PNG 目录）

    与 build_list 的区别：这里不是「算出还缺什么」，而是「盘点已经写了什么」。
    每个字实际写了几种 = 该字在目录里的 PNG 张数（`uniXXXX.png` + `uniXXXX_NN.png`…）。
    PNG 文件名里带 `_NN` 的就是变体序号（见 docs/font-variants.md）。

    Returns: [(char, codepoint, category, png_count, variants, filenames), ...]
    """
    pat = re.compile(r'^u(?:ni)?([0-9A-Fa-f]{4,6})(?:_(\d+))?\.png$')
    per_char = {}
    for name in sorted(os.listdir(images_dir)):
        m = pat.match(name)
        if not m:
            continue
        cp = int(m.group(1), 16)
        per_char.setdefault(cp, []).append(name)
    # 按 PNG 张数降序（= 写得最多的字在前），同数按码点升序
    items = []
    for cp, files in sorted(per_char.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        items.append((chr(cp), cp, classify(chr(cp)), len(files),
                      len(files) if uniform <= 0 else uniform, files))
    return items


def main():
    ap = argparse.ArgumentParser(
        description='书写清单生成（算出该补写哪些字、每个字写几种写法）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument('--font', default='',
                    help='当前字库 TTF（用它判断哪些字还缺）')
    ap.add_argument('--doc', default=[], nargs='+',
                    help='目标文档（可给多篇；多篇时字频合并累计）')
    # 注意：action='append' 不能配 default=''（argparse 会把字符串当列表 append）
    ap.add_argument('--exclude-csv', action='append',
                    help='额外的排除清单 CSV（可重复、支持通配符；如 "书写清单*.csv"）')
    ap.add_argument('--images-dir', default='',
                    help='改为盘点模式：统计该素材目录里**已经写好**的字形（不从文档算）')
    ap.add_argument('--out', required=True, help='书写清单 CSV 输出路径')
    ap.add_argument('--limit', type=int, default=0,
                    help='只取优先级最高的前 N 个字（0 = 全部；数字 0-9 不受此限制）')
    ap.add_argument('--uniform', type=int, default=0,
                    help='每个字强制写这么多种（0 = 用字频分档）')
    args = ap.parse_args()

    # ---- 盘点模式：统计已写字形 ----
    if args.images_dir:
        if not os.path.isdir(args.images_dir):
            sys.exit(f'素材目录不存在: {args.images_dir}')
        written = build_written_list(args.images_dir)
        with open(args.out, 'w', encoding='utf-8-sig', newline='') as f:
            wr = csv.writer(f)
            wr.writerow(['priority', 'char', 'unicode', 'category',
                         'png_count', 'variants_written', 'glyph_name', 'png_files'])
            for i, (ch, cp, cat, n_png, n, files) in enumerate(written, 1):
                wr.writerow([i, ch, f'U+{cp:04X}', cat, n_png, n,
                             fontlab_filename(cp)[:-4], ';'.join(files)])
        tot = sum(n for *_x, n, _f in written)
        multi = sum(1 for *_x, n, _f in written if n > 1)
        print(f'盘点目录  : {os.path.abspath(args.images_dir)}')
        print(f'已写字形  : {tot:,} 个（{len(written):,} 个不同字）')
        print(f'有多种写法的字: {multi:,} 个')
        print(f'\n已写清单已写入: {os.path.abspath(args.out)}')
        return

    # ---- 正常模式：从文档算还需补哪些字 ----
    if not args.font:
        sys.exit('--font 必填（或用 --images-dir 走盘点模式）')
    if not args.doc:
        sys.exit('--doc 必填（或用 --images-dir 走盘点模式）')
    if not os.path.isfile(args.font):
        sys.exit(f'字库不存在: {args.font}')
    for p in args.doc:
        if not os.path.isfile(p):
            sys.exit(f'文档不存在: {p}')

    exclude = set()
    for pattern in (args.exclude_csv or []):
        # 支持通配符：--exclude-csv "书写清单*.csv" 可一次排除全部历史清单
        matched = sorted(glob.glob(pattern)) if any(c in pattern for c in '*?[') else [pattern]
        if not matched:
            print(f'⚠️ --exclude-csv 没匹配到文件（忽略）: {pattern}')
            continue
        for c in matched:
            if not os.path.isfile(c):
                sys.exit(f'排除清单不存在: {c}')
            got = load_csv_chars(c)
            exclude |= got
            print(f'排除清单  : {os.path.basename(c)} → {len(got):,} 字')
    if exclude:
        print(f'排除合计  : {len(exclude):,} 字')

    items = build_list(args.doc, load_font_chars(args.font),
                       args.limit, args.uniform, exclude)

    with open(args.out, 'w', encoding='utf-8-sig', newline='') as f:
        wr = csv.writer(f)
        wr.writerow(['priority', 'char', 'unicode', 'category', 'count',
                     'variants_to_write', 'glyph_name'])
        for i, (ch, cp, cat, cnt, n) in enumerate(items, 1):
            wr.writerow([i, ch, f'U+{cp:04X}', cat, cnt, n,
                         fontlab_filename(cp)[:-4]])

    total_glyphs = sum(n for *_x, n in items)
    print(f'字库      : {os.path.abspath(args.font)}')
    for p in args.doc:
        print(f'文档      : {os.path.abspath(p)}')
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
