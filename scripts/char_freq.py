# -*- coding: utf-8 -*-
"""字频统计 —— 为制作个人字库 TTF 挑字

统计任意文本（含 Markdown）的字符频率，输出：
  - 总字符数 / 去重字符数
  - 分类统计（汉字 / 数字 / 字母 / 标点符号 / 空白 / 其他）
  - 高频字 Top N
  - 汉字累积覆盖率（手写前 N 个字能覆盖正文多少比例的汉字出现次数）
  - 去重字符表 CSV（按字频降序，含 TTF 建库所需的字形名/PNG 名映射）

算法（高速关键，4 点）：
  1. 字节一次读入 → 解码一次，不用 readline 逐行（减少 syscall 与解码次数）
  2. Counter(text) 走 CPython 的 C 层 _count_elements 单遍计数，O(n)
  3. 分类只对**去重后**的字符做（u 个），不是对全部 n 个字符做 → O(u) 而非 O(n)
     （本文档 n=39,376、u=1,409，分类开销降约 28 倍）
  4. 全程只扫一遍文本。naive 写法如 text.count(c) 逐字重扫是 O(n·u)
     本文档实测: Counter 7.8ms / 手写 dict 循环 9.4ms / text.count 逐字 50.6ms

  注：本文件规模下三者都是毫秒级，差异可忽略；算法选择的意义在于 n 变大时
      （如整个语料库）O(n) 与 O(n·u) 的差距会线性放大

用法：
  python scripts/char_freq.py <文件> [--top 50] [--out 报告.txt]
                                   [--charset 字符表.csv] [--font 字库.ttf]

  --top     高频表显示条数（默认 50）
  --out     把完整报告写入文件（默认只打印到控制台）
  --font    一个 TTF 路径：额外输出「本文档 vs 该字库」的覆盖率与缺失字清单
            口径 = 建字库口径；缺失字按文档字频降序，直接就是「该补写哪些字」
  --charset 额外导出「去重非空白字符表」CSV（制字 / 建 TTF 用），列为:
              unicode, char, category, glyph_name, png_filename, count, in_font
            glyph_name  = uni4E00 / u20000     ← TTF 里的字形名
            png_filename= uni4E00_一.png       ← 预处理工具导出的 PNG 名
            category    = 汉字/数字/字母/中文标点/西文标点/空白/其他
                          建字库口径: category in (汉字, 数字, 中文标点)
                          （中文标点按东亚宽度 W/F/A 判定, 故 “”‘’—… 算中文标点,
                            而 Markdown 的 # | -&gt; * . % / 算西文标点, 自然被筛掉）
            in_font     = 该字符是否已被 --font 字库收录（未给 --font 时为空）
                          → 补字清单 = 筛 category 属建字库口径 且 in_font=False
            以 utf-8-sig 写出, Excel 双击不乱码

依赖：
  - utils/charset_utils.py（is_cjk / fontlab_filename / GB2312·GBK 字符集）
  - fontTools（仅 --font 时用，读原始 cmap）
  - 标准库 collections / unicodedata
"""

import argparse
import csv
import os
import sys
import time
import unicodedata
from collections import Counter


sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from utils.charset_utils import is_cjk, fontlab_filename  # noqa: E402

# 编码尝试顺序：BOM → 纯 UTF-8 → GB18030（GBK/GB2312 的超集，几乎不会失败，放最后兜底）
ENCODINGS = ('utf-8-sig', 'utf-8', 'gb18030')

# 数字：ASCII + 全角
DIGITS = set('0123456789０１２３４５６７８９')

CATEGORIES = ('汉字', '数字', '字母', '中文标点', '西文标点', '空白', '其他')

# 「建字库口径」：判断一套字库能不能排出这篇文档时只算这几类。
# 西文标点（Markdown 的 # | - > * . % / 等）与拉丁字母是文档格式产物，排版前会清掉。
FONT_SCOPE = ('汉字', '数字', '中文标点')


def read_text(path):
    """一次读入并解码，返回 (text, encoding)"""
    with open(path, 'rb') as f:
        raw = f.read()
    for enc in ENCODINGS:
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    sys.exit(f"解码失败（试过 {', '.join(ENCODINGS)}）: {path}")


def classify(ch):
    """把单个字符归类（只对去重后的字符调用）"""
    if is_cjk(ord(ch)):
        return '汉字'
    if ch.isspace():
        return '空白'
    # Unicode 大类 N*=数字，比硬编码数字集更全（含全角０-９、〇 U+3007、①、Ⅷ 等）
    cat = unicodedata.category(ch)
    if ch in DIGITS or cat[0] == 'N':
        return '数字'
    if ('a' <= ch <= 'z') or ('A' <= ch <= 'Z'):
        return '字母'
    # P*=标点, S*=符号（含数学符号、货币符号等）
    if cat[0] in ('P', 'S'):
        # 按东亚宽度细分——建字库时这个区分才有用:
        #   W(宽)/F(全角) = ，。、；：（）《》！  等中文标点
        #   A(歧义)       = “”‘’—…· 等中文弯引号/破折号（Unicode 归为歧义宽度）
        #   Na(窄)        = # | - > * . % / 等 ASCII 符号 → Markdown 格式符号在这里
        return '中文标点' if unicodedata.east_asian_width(ch) in ('W', 'F', 'A') else '西文标点'
    return '其他'


def display(ch):
    """打印用：空白字符不可见，替换成可见名（\t 在表格里会撑坏排版）"""
    if ch == ' ':
        return '<空格>'
    if ch == '\t':
        return '<Tab>'
    if ch == '\n':
        return '<换行>'
    if ch == '\r':
        return '<回车>'
    if ch.isspace():
        return f'<{unicodedata.name(ch, "空白")}>'
    return ch


def _width(s):
    """字符串在等宽终端里的显示列宽（CJK 全角算 2 列）"""
    return sum(2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1 for c in s)


def _pad(s, width, align='>'):
    """按显示列宽补齐——不能用 str.rjust，那按字符数补，遇全角必错位"""
    fill = ' ' * max(0, width - _width(s))
    return fill + s if align == '>' else s + fill


def cumulative_coverage(ordered_chars, freq):
    """按字频降序累加，返回 [(前k个字, 累积覆盖次数), ...]（只算给定字符集合）"""
    total = sum(freq[c] for c in ordered_chars)
    pts, acc = [], 0
    for i, c in enumerate(ordered_chars, 1):
        acc += freq[c]
        pts.append((i, acc, total))
    return pts


def main():
    ap = argparse.ArgumentParser(
        description='字频统计（为制作个人字库 TTF 挑字）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument('file', help='待统计的文本文件（.md/.txt/.docx 导出的文本等）')
    ap.add_argument('--top', type=int, default=50, help='高频表显示条数（默认 50）')
    ap.add_argument('--out', default='', help='把完整报告写入该文件（默认只打印）')
    ap.add_argument('--charset', default='', help='导出去重字符表（制字用）到该文件')
    ap.add_argument('--font', default='',
                    help='TTF 路径：额外输出「本文字符 vs 该字库」的覆盖率与缺失字清单')
    args = ap.parse_args()

    if not os.path.isfile(args.file):
        sys.exit(f'文件不存在: {args.file}')

    # 若给了 --font，先读入该字库的字符集（报告与 CSV 共用）
    font_chars = set()
    font_han = 0
    if args.font:
        if not os.path.isfile(args.font):
            sys.exit(f'字体不存在: {args.font}')
        from fontTools.ttLib import TTFont
        from utils.charset_utils import is_cjk
        try:
            _ft = TTFont(args.font)
            _cmap = _ft.getBestCmap() or {}
            _ft.close()
        except Exception as e:
            sys.exit(f'读取字体失败: {args.font}: {e}')
        # ★ 这里读**原始 cmap**，不能用 utils.charset_utils.get_font_chars()：
        #   那个函数按设计只返回「汉字」，内部用 is_cjk 过滤，而 CJK_RANGES 不含
        #   。(U+3002) 、， (U+FF0C) ！？ 等 CJK 标点 —— 会把字库里明明有的高频标点
        #   误判成「缺失」（实测会低估覆盖率约 7 个百分点）。
        #   is_cjk 只用在这里做「其中多少个是汉字」的统计，不当过滤条件。
        #   另注：将来的 PUA 变体码点（U+E000+）不是 CJK，但每个字的主码点仍在 cmap 里，
        #   所以不会把「已收录」误判成缺失（详见 docs/font-variants.md）。
        font_chars = {chr(cp) for cp in _cmap}
        font_han = sum(1 for c in font_chars if is_cjk(ord(c)))

    t0 = time.perf_counter()
    text, enc = read_text(args.file)
    t_read = time.perf_counter() - t0

    t1 = time.perf_counter()
    freq = Counter(text)                       # C 层单遍计数, O(n)
    t_count = time.perf_counter() - t1

    t2 = time.perf_counter()
    cats = {ch: classify(ch) for ch in freq}   # 只分类去重字符, O(u)
    t_classify = time.perf_counter() - t2

    # ---- 汇总 ----
    n_total = len(text)
    n_uniq = len(freq)
    by_cat = {c: {'total': 0, 'uniq': 0} for c in CATEGORIES}
    for ch, cnt in freq.items():
        e = by_cat[cats[ch]]
        e['total'] += cnt
        e['uniq'] += 1

    han = [c for c in freq if cats[c] == '汉字']
    han.sort(key=lambda c: (-freq[c], ord(c)))
    cov = cumulative_coverage(han, freq)
    han_total = sum(freq[c] for c in han)

    out = []

    def w(line=''):
        out.append(line)

    w('=' * 74)
    w('字频统计报告')
    w('=' * 74)
    w(f'文件      : {os.path.abspath(args.file)}')
    w(f'编码      : {enc}')
    w(f'总字符数  : {n_total:,}   （含空白与标点）')
    w(f'去重字符数: {n_uniq:,}')
    w('')
    w(f'读盘+解码 {t_read*1000:8.1f} ms')
    w(f'计数      {t_count*1000:8.1f} ms   ← Counter(text), C 层单遍 O(n)')
    w(f'分类      {t_classify*1000:8.1f} ms   ← 只分类去重后的 {n_uniq:,} 个字符, O(u)')
    w(f'合计      {(t_read+t_count+t_classify)*1000:8.1f} ms')
    w('')

    # ---- 分类统计 ----
    w('-' * 74)
    w('分类统计')
    w('-' * 74)
    w(f'{"类别":<8}{"出现次数":>12}{"占比":>10}{"去重字数":>10}')
    for c in CATEGORIES:
        e = by_cat[c]
        if e['total'] == 0:
            continue
        pct = e['total'] / n_total * 100
        w(f'{c:<8}{e["total"]:>12,}{pct:>9.2f}%{e["uniq"]:>10,}')
    w('')

    # ---- 高频字 Top N ----
    top = freq.most_common(args.top)
    w('-' * 74)
    w(f'高频字符 Top {args.top}')
    w('-' * 74)
    per_row = 10
    for i in range(0, len(top), per_row):
        cells = []
        for ch, cnt in top[i:i + per_row]:
            cells.append(_pad(display(ch), 4) + _pad(str(cnt), 6))
        w('  ' + '  '.join(cells))
    w('')

    # ---- 汉字累积覆盖率（决定手写多少个字）----
    w('-' * 74)
    w('汉字累积覆盖率 —— 手写前 N 个字能覆盖正文多少汉字')
    w('-' * 74)
    w(f'本文档共出现汉字 {han_total:,} 次, 去重后 {len(han):,} 个字')
    w('')
    w(f'{"手写字数":>10}{"覆盖汉字次数":>16}{"覆盖率":>10}')
    marks = [50, 100, 200, 300, 500, 800, 1000, 1500, 2000, 3000, 4000, 5000, 6763]
    marks = [m for m in marks if m <= len(han)]
    if len(han) not in marks:
        marks.append(len(han))
    for m in marks:
        k, acc, tot = cov[m - 1]
        w(f'{k:>10,}{acc:>16,}{acc/tot*100:>9.2f}%')
    w('')

    # ---- 对标 GB2312 / GBK ----
    try:
        from utils.charset_utils import get_charset
        w('-' * 74)
        w('对标标准字符集（本文档汉字集 vs GB2312 / GBK）')
        w('-' * 74)
        # 注意：get_charset() 返回的是**码点集合 set[int]**，而 han 是字符 list[str]，
        # 两者不能直接比较（str in set[int] 恒为 False），必须先转成码点
        han_cps = {ord(c) for c in han}
        w(f'{"字符集":<10}{"收录汉字":>12}{"本文档命中":>12}{"命中率":>10}{"未收录":>10}')
        for name in ('GB2312', 'GBK'):
            cs = get_charset(name)
            if not cs:
                continue
            hit = han_cps & cs
            miss_cps = han_cps - cs
            w(f'{name:<10}{len(cs):>12,}{len(hit):>12,}'
              f'{len(hit)/len(han_cps)*100:>9.2f}%{len(miss_cps):>10,}')
            if miss_cps:
                miss = sorted((chr(cp) for cp in miss_cps), key=lambda c: (-freq[c], ord(c)))
                w(f'   未收录: {"".join(miss)}')
        w('')
    except Exception as e:
        w(f'（跳过标准字符集对比: {e}）')
        w('')

    # ---- 对标个人字库 TTF（这套字能不能排出这篇文档）----
    # 口径 = 建字库口径（汉字 + 数字 + 中文标点）：Markdown 符号与拉丁字母是文档格式产物，
    # 排版前会被清掉，不该算进「字库够不够用」。
    if args.font:
        scope = [c for c in freq if cats[c] in FONT_SCOPE]
        scope.sort(key=lambda c: (-freq[c], ord(c)))
        have = [c for c in scope if c in font_chars]
        miss = [c for c in scope if c not in font_chars]
        n_scope = sum(freq[c] for c in scope)
        n_miss = sum(freq[c] for c in miss)
        n_have = n_scope - n_miss
        w('-' * 74)
        w('对标个人字库 TTF（口径: 汉字 + 数字 + 中文标点）')
        w('-' * 74)
        w(f'字库         : {os.path.abspath(args.font)}')
        w(f'字库收录字符 : {len(font_chars):,}   '
          f'（其中汉字 {font_han:,}，其余 {len(font_chars)-font_han:,} 为标点/数字/字母）')
        w('')
        w(f'本文档该口径字符 : {len(scope):,} 个 / 出现 {n_scope:,} 次')
        w(f'  ├ 字库已收录  : {len(have):>6,} 个   '
          f'覆盖 {n_have/n_scope*100:>6.2f}% 的字符出现次数')
        w(f'  └ ★ 还需补写  : {len(miss):>6,} 个   '
          f'占 {n_miss/n_scope*100:>6.2f}%')
        w('')
        if miss:
            w('补齐建议（按文档字频降序，前 N 个缺失字能盖住多少）:')
            w(f'{"补写字数":>10}{"新增覆盖次数":>16}{"新增覆盖率":>12}{"累计覆盖率":>12}')
            marks = [50, 100, 200, 300, 500, 800, 1000, 1500, 2000, 3000, 4000]
            marks = [m for m in marks if m < len(miss)] + [len(miss)]
            for m in marks:
                add = sum(freq[c] for c in miss[:m])
                w(f'{m:>10,}{add:>16,}{add/n_scope*100:>11.2f}%'
                  f'{(n_have+add)/n_scope*100:>11.2f}%'
                  + ('   ← 补满' if m == len(miss) else ''))
            w('')
            w('缺失字（按字频降序）:')
            show, per_row = miss[:200], 40
            for i in range(0, len(show), per_row):
                w('  ' + ''.join(show[i:i + per_row]))
            if len(miss) > len(show):
                w(f'  ...（共 {len(miss):,} 个，完整清单筛 --charset 导出 CSV 的 in_font 列）')
        w('')

    report = '\n'.join(out)
    print(report)

    if args.out:
        with open(args.out, 'w', encoding='utf-8') as f:
            f.write(report + '\n')
        print(f'\n报告已写入: {os.path.abspath(args.out)}')

    # ---- 去重字符表（制字 / 建 TTF 用，CSV）----
    if args.charset:
        # 非空白字符，按字频降序；同频按码点升序，保证可复现
        chars = [c for c in freq if not c.isspace()]
        chars.sort(key=lambda c: (-freq[c], ord(c)))
        # utf-8-sig 带 BOM → Excel 双击不乱码；newline='' 是 csv 模块的硬性要求
        with open(args.charset, 'w', encoding='utf-8-sig', newline='') as f:
            wr = csv.writer(f)
            wr.writerow(['unicode', 'char', 'category',
                         'glyph_name', 'png_filename', 'count', 'in_font'])
            for c in chars:
                cp = ord(c)
                wr.writerow([
                    f'U+{cp:04X}',            # 码点
                    c,                         # 字符本身
                    cats[c],                   # 汉字/数字/字母/中文标点/西文标点/其他
                    fontlab_filename(cp)[:-4], # uni4E00 / u20000     ← TTF 字形名
                    fontlab_filename(cp, c),   # uni4E00_一.png       ← 预处理导出的 PNG 名
                    freq[c],                   # 出现次数
                    # 是否已被 --font 指定的字库收录（'' = 未给 --font）
                    (c in font_chars) if args.font else '',
                ])
        print(f'字符表(CSV)已写入: {os.path.abspath(args.charset)} （{len(chars):,} 字符）')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
