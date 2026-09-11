# -*- coding: utf-8 -*-
"""渲染副本生成 —— 把文本里的字随机换成它的某个变体写法

配合 scripts/build_variant_ttf.py 产出的「带 PUA 变体的 TTF」使用：
变体字形挂在私用区码点（U+E000 起）上，本脚本把正文里的一部分字替换成对应的 PUA 码点，
这样用那套字库渲染出来，**同一个字在文章不同位置就是不同的写法**，更像真实手写。

    原稿:   我们的党
    替换后: 我们{U+E003}的党          ← 「的」用了第 3 种写法

## ⚠️ 两个必须知道的限制

1. **替换后的文本不再可读** —— PUA 码点在编辑器里显示为空白框/豆腐块，搜索"的"也搜不到。
   所以**只在渲染副本上做**，原稿不要动（本脚本默认就输出到另一个文件）。
2. **只有写了多种写法的字才有变体**。当前字库里只有 50 个字符有变体
   （的 25 种、党 13 种…），其余字符只有一种写法，替换对它们无效。

## 用法

  python scripts/make_variant_text.py 原稿.txt \\
      --map font/variant_map.json --out 渲染副本.txt [--seed 42]

  # 换一版随机结果：改 --seed
  python scripts/make_variant_text.py 原稿.txt --map ... --out 副本2.txt --seed 7

替换规则：对每个「有变体的字」，在 **[主字形 + 它的所有变体]** 中等概率随机取一个。
所以主字形仍会以 1/(n+1) 的概率出现（n = 该字的变体数）。

输出仍是 UTF-8 文本，换行与段落结构原样保留，可直接喂给 handwriter 渲染。

依赖：仅标准库
"""

import argparse
import json
import os
import random
import sys

# 与 handwriter 一致的编码尝试顺序
ENCODINGS = ('utf-8-sig', 'utf-8', 'gb18030', 'gbk')


def read_text(path):
    with open(path, 'rb') as f:
        raw = f.read()
    for enc in ENCODINGS:
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    sys.exit(f'解码失败（试过 {", ".join(ENCODINGS)}）: {path}')


def load_map(path):
    """读变体映射表 → {字符: [候选码点int, ...]}（含主码点，供等概率选取）"""
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    choices = {}
    for ch, obj in data.get('chars', {}).items():
        cps = []
        main = obj.get('main')
        if main:
            cps.append(int(main.replace('U+', ''), 16))
        for v in obj.get('variants', []):
            cps.append(int(v.replace('U+', ''), 16))
        if cps:
            choices[ch] = cps
    return choices, data


def main():
    ap = argparse.ArgumentParser(
        description='把文本里的字随机换成它的变体写法（供 handwriter 渲染手写风格）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument('file', help='原稿文本（.txt/.md 等纯文本）')
    ap.add_argument('--map', required=True, help='变体映射表 JSON（build_variant_ttf.py 产出）')
    ap.add_argument('--out', required=True, help='渲染副本输出路径（不要等于原稿）')
    ap.add_argument('--seed', type=int, default=0,
                    help='随机种子（默认 0 = 可复现；换个数字得到另一版随机结果）')
    ap.add_argument('--only', default='',
                    help='只替换这些字符（如 "的党"，排查问题用；留空 = 全部有变体的字）')
    args = ap.parse_args()

    if os.path.abspath(args.out) == os.path.abspath(args.file):
        sys.exit('--out 不能等于原稿（替换后不可读，请输出到另一个文件）')
    for p, label in ((args.file, '原稿'), (args.map, '映射表')):
        if not os.path.isfile(p):
            sys.exit(f'{label}不存在: {p}')

    choices, meta = load_map(args.map)
    if not choices:
        sys.exit('映射表里没有任何变体（先用 build_variant_ttf.py 构建）')
    if args.only:
        choices = {k: v for k, v in choices.items() if k in args.only}
        if not choices:
            sys.exit(f'--only 指定的字符都不在映射表里: {args.only}')

    text, enc = read_text(args.file)
    rng = random.Random(args.seed)

    out_chars = []
    n_hit = n_sub = 0
    used = {}
    for ch in text:
        cps = choices.get(ch)
        if not cps:
            out_chars.append(ch)
            continue
        n_hit += 1
        cp = rng.choice(cps)
        out_chars.append(chr(cp))
        used[cp] = used.get(cp, 0) + 1
        if cp != ord(ch):
            n_sub += 1

    with open(args.out, 'w', encoding='utf-8', newline='') as f:
        f.write(''.join(out_chars))

    rep = [cp for cp in used if cp >= 0xE000]
    print(f'原稿        : {os.path.abspath(args.file)}  (编码 {enc})')
    print(f'映射表      : {os.path.abspath(args.map)}')
    print(f'  可替换字符: {len(choices):,} 个  （来自 base: {meta.get("base_ttf","?")}）')
    print(f'随机种子    : {args.seed}')
    print()
    print(f'文本总字符  : {len(text):,}')
    print(f'  命中可替换: {n_hit:,} 次')
    print(f'  实际替换成变体写法: {n_sub:,} 次'
          f'（{n_sub/n_hit*100:.1f}%；其余保持主字形）' if n_hit else '')
    print(f'  用到的 PUA 变体码点: {len(rep):,} 个')
    print()
    print(f'渲染副本已写入: {os.path.abspath(args.out)}')
    print('⚠️ 该文件不可读（PUA 码点在编辑器里是空白框），仅供 handwriter 渲染用')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
