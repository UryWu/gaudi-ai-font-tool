# -*- coding: utf-8 -*-
"""外部字形图像组装 - 把 PNG 直接拼成引擎要的 1024×256 复合训练图

不依赖 zi2zi-JiT 引擎，只用 fontTools + Pillow + numpy。

引擎 FontSrcTargetRefsDataset（zi2zi-JiT/main_jit.py:24）吃的复合图结构：
  0-256    : source  (标准字形 from source_font)
  256-512  : target  (个人字形 from images_dir)
  512-768  : ref grid 0-3
  768-1024 : ref grid 4-7
  每格 128×128

文件名约定（与 train_manager.prepare_data 保持一致）：
  {idx:05d}_{char}.png   idx 从 0 开始连续
"""

import os
import sys
import csv
import glob
import re
import json
from typing import List, Tuple, Optional


# 与 train_manager REF_CHARS 保持一致（优先级 8 字）
DEFAULT_REF_CHARS = ['永', '和', '之', '道', '心', '人', '大', '天']


def _open_image_white(path: str, size: int) -> 'PIL.Image.Image':
    """打开图片，转灰度，按 size 居中缩放并贴到白底（避免 alpha 透明）"""
    from PIL import Image
    im = Image.open(path)
    if im.mode != 'L':
        im = im.convert('L')
    # 缩放：等比缩到不超过 size，留白居中
    im.thumbnail((size, size), Image.Resampling.LANCZOS)
    canvas = Image.new('L', (size, size), 255)
    x = (size - im.width) // 2
    y = (size - im.height) // 2
    canvas.paste(im, (x, y))
    return canvas


def _load_source_renderer(source_font: str, resolution: int):
    """加载 source 渲染器（用 fontTools + PIL，因为 zi2zi 引擎依赖重型）

    返回 (render_fn, available_chars_set)
    render_fn(codepoint: int) -> PIL.Image.Image or None
    """
    from fontTools.ttLib import TTFont
    from PIL import Image, ImageDraw, ImageFont

    font = TTFont(source_font)
    cmap = font.getBestCmap() or {}
    available = set(cmap.keys())
    font.close()

    # 估算字号：resolution 像素下需要多大字号
    # 经验值：font_size = resolution * 1.4
    font_size = int(resolution * 1.4)

    pil_font = ImageFont.truetype(source_font, font_size)

    def render(cp: int) -> Optional[Image.Image]:
        if cp not in available:
            return None
        ch = chr(cp)
        img = Image.new('L', (resolution, resolution), 255)
        draw = ImageDraw.Draw(img)
        # 用 fontTools 的 metrics 计算居中
        try:
            ascent, descent = pil_font.getmetrics()
            text_width = draw.textlength(ch, font=pil_font)
            x = (resolution - text_width) // 2
            y = (resolution - ascent) // 2
        except Exception:
            x = resolution // 4
            y = resolution // 4
        draw.text((x, y), ch, fill=0, font=pil_font)
        return img

    return render, available


def _scan_images_dir(images_dir: str) -> List[Tuple[str, str, int]]:
    """扫描 images_dir，返回 [(png_path, char_str, codepoint), ...]

    优先按 source_map.json 解析（scaled_NNNN.png → 真实 unicode 字符）；
    否则按文件名 `uniXXXX.png` 解析 unicode；
    最后回退到 `uniXXXX_字.png` 形式（取 _ 后的字）。

    char 缺失或 unicode 越界则跳过。
    """
    items = []
    # 1) 优先 source_map.json（兼容多种位置）
    sm_candidates = [
        os.path.join(images_dir, 'source_map.json'),
        os.path.join(os.path.dirname(images_dir), 'source_map.json'),
        os.path.join(os.path.dirname(images_dir), 'exported', 'source_map.json'),
        # gaudi-font-preprocess 标准布局：session_dir/exported/ 下常有 *_source_map.json
    ]
    # 再加：父级 exported 下任何 *_source_map.json
    parent = os.path.dirname(images_dir)
    if os.path.isdir(os.path.join(parent, 'exported')):
        for f in os.listdir(os.path.join(parent, 'exported')):
            if f.endswith('.source_map.json'):
                sm_candidates.append(os.path.join(parent, 'exported', f))

    sm = next((p for p in sm_candidates if os.path.isfile(p)), None)

    if sm:
        try:
            with open(sm, 'r', encoding='utf-8') as f:
                mapping = json.load(f)
            inv = {}
            for src, dst in mapping.items():
                src_png = os.path.join(images_dir, src)
                if not os.path.isfile(src_png):
                    continue
                if isinstance(dst, str):
                    m = re.match(r'uni([0-9A-Fa-f]+)(?:_\d+)?(?:\.png)?$', dst)
                    if m:
                        cp = int(m.group(1), 16)
                    else:
                        continue
                elif isinstance(dst, dict):
                    cp = int(dst.get('unicode', '0').replace('U+', ''), 16)
                else:
                    continue
                if cp <= 0 or cp > 0x10FFFF:
                    continue
                inv[src_png] = (chr(cp), cp)
            items = [(p, c, cp) for p, (c, cp) in inv.items()]
        except Exception:
            items = []

    # 2) fallback: 按文件名 uniXXXX.png 解析
    if not items:
        for path in sorted(glob.glob(os.path.join(images_dir, '*.png'))):
            name = os.path.basename(path)
            m = re.match(r'uni([0-9A-Fa-f]+)(?:_\d+)?$', name.replace('.png', ''))
            if not m:
                continue
            cp = int(m.group(1), 16)
            if cp <= 0 or cp > 0x10FFFF:
                continue
            items.append((path, chr(cp), cp))

    # 3) 再 fallback: 文件名带字
    if not items:
        for path in sorted(glob.glob(os.path.join(images_dir, '*.png'))):
            name = os.path.basename(path).replace('.png', '')
            parts = name.split('_', 1)
            if len(parts) == 2 and parts[1]:
                ch = parts[1]
                if len(ch) == 1:
                    items.append((path, ch, ord(ch)))

    return items


def assemble_composites(
    images_dir: str,
    source_font: str,
    output_data_dir: str,
    resolution: int = 256,
    ref_size: int = 128,
    ref_chars: Optional[List[str]] = None,
    max_chars: Optional[int] = None,
    invert: bool = False,
) -> dict:
    """扫描 images_dir 下的 PNG，按引擎契约拼复合图写到 output_data_dir/001_font/

    Args:
        images_dir: 个人字形 PNG 目录（如 gaudi-font-preprocess 的 scaled/）
        source_font: source 通道用的 TTF（用 PIL ImageFont 渲染，避免依赖 zi2zi 引擎）
        output_data_dir: 落盘根，会建 001_font/ 子目录
        resolution: source/target 通道尺寸
        ref_size: ref 网格单字尺寸
        ref_chars: ref 网格 8 字（缺省用 DEFAULT_REF_CHARS）
        max_chars: 限制字符数（None=全部）
        invert: 是否反色（深底浅字 → 浅底深字；适配 PIL text 默认绘制）

    Returns:
        {"char_count": int, "data_dir": str, "skipped": int}
    """
    from PIL import Image, ImageOps

    if ref_chars is None:
        ref_chars = DEFAULT_REF_CHARS

    items = _scan_images_dir(images_dir)
    if not items:
        return {"char_count": 0, "data_dir": output_data_dir, "skipped": 0,
                "error": f"在 {images_dir} 找不到可识别的 PNG（需 source_map.json 或 uniXXXX.png 命名）"}

    if max_chars:
        items = items[:max_chars]

    render_src, src_available = _load_source_renderer(source_font, resolution)

    # ref 网格 = 风格参考，必须全部来自个人字迹
    # （引擎每张图随机抽 1 格作风格锚点；若用系统字体，会污染风格条件）
    item_chars = {ch for _, ch, _ in items}
    ref_chars_eff = []
    used = set()
    # 1) 先用默认 8 字中确实存在于个人字迹的
    for c in ref_chars:
        if c in item_chars and c not in used:
            ref_chars_eff.append(('item', c))
            used.add(c)
    # 2) 不足则从个人字迹里按顺序补齐
    for _, ch, _ in items:
        if len(ref_chars_eff) >= len(ref_chars):
            break
        if ch not in used:
            ref_chars_eff.append(('item', ch))
            used.add(ch)
    # 3) 极端情况（个人字迹总数 < ref 格数）才用 source_font 兜底
    idx = 0
    while len(ref_chars_eff) < len(ref_chars):
        ref_chars_eff.append(('render', ref_chars[idx % len(ref_chars)]))
        idx += 1

    os.makedirs(output_data_dir, exist_ok=True)
    font_dir = os.path.join(output_data_dir, '001_font')
    os.makedirs(font_dir, exist_ok=True)

    # 预渲染 8 个 ref 字
    ref_cells = []
    for kind, ch in ref_chars_eff:
        if kind == 'item':
            png_path = next(p for p, c, _ in items if c == ch)
            cell = _open_image_white(png_path, ref_size)
        else:
            cp = ord(ch)
            rendered = render_src(cp)
            if rendered is None:
                # 最后兑底：白图
                cell = Image.new('L', (ref_size, ref_size), 255)
            else:
                cell = rendered.resize((ref_size, ref_size), Image.Resampling.LANCZOS).convert('L')
        if invert:
            cell = ImageOps.invert(cell)
        ref_cells.append(cell)

    success = 0
    skipped = 0
    for idx, (png_path, ch, cp) in enumerate(items):
        try:
            # target: 个人字形 PNG
            target = _open_image_white(png_path, resolution)
            if invert:
                target = ImageOps.invert(target)

            # source: source_font 渲染同字
            src = render_src(cp)
            if src is None:
                skipped += 1
                continue
            if invert:
                src = ImageOps.invert(src.convert('L'))
            else:
                src = src.convert('L')

            # 拼 1024×256 复合图
            composite = Image.new('L', (1024, 256), 255)
            composite.paste(src, (0, 0))
            composite.paste(target, (256, 0))

            # ref 网格：左 4 格、右 4 格
            for i, cell in enumerate(ref_cells[:4]):
                grid = (i // 2) * ref_size
                composite.paste(cell, (512 + (i % 2) * ref_size, grid))
            for i, cell in enumerate(ref_cells[4:]):
                grid = (i // 2) * ref_size
                composite.paste(cell, (768 + (i % 2) * ref_size, grid))

            out_name = f"{success:05d}_{ch}.png"
            composite.save(os.path.join(font_dir, out_name))
            success += 1
        except Exception:
            skipped += 1
            continue

    return {
        "char_count": success,
        "data_dir": output_data_dir,
        "skipped": skipped,
    }


def write_test_npz(
    data_dir: str,
    source_font: str,
    ref_font: Optional[str] = None,
    resolution: int = 256,
    ref_size: int = 128,
) -> str:
    """为 train_manager 兼容而写的 test.npz（实际上训练不消费，但 app.py 门禁需要）

    ref_font 缺省时降级为 source_font（保持门禁通过）。
    返回 test.npz 路径。
    """
    import numpy as np
    from PIL import Image

    if ref_font is None:
        ref_font = source_font

    render_src, _ = _load_source_renderer(source_font, resolution)
    # style_image: 渲染「永」（与 train_manager 行为一致）
    yong_img = render_src(ord('永'))
    if yong_img is None:
        yong_img = Image.new('L', (resolution, resolution), 255)
    yong_l = yong_img.convert('L').resize((ref_size, ref_size), Image.Resampling.LANCZOS)
    # (H,W) → (3,H,W) 形式（train_manager 写的是 3 通道）
    style_array = np.stack([np.array(yong_l)] * 3, axis=0)

    font_dir = os.path.join(data_dir, '001_font')
    files = sorted([f for f in os.listdir(font_dir) if f.endswith('.png')])[:50]
    font_labels, char_labels, content_images, unicode_labels = [], [], [], []

    for idx, f in enumerate(files):
        parts = f.replace('.png', '').split('_', 1)
        char_name = parts[1] if len(parts) > 1 else ''
        codepoint = ord(char_name[0]) if char_name else 0
        src_img = render_src(codepoint)
        if src_img is None:
            continue
        src_l = src_img.convert('L').resize((resolution, resolution), Image.Resampling.LANCZOS)
        content_array = np.stack([np.array(src_l)] * 3, axis=0)
        font_labels.append(0)
        char_labels.append(idx)
        content_images.append(content_array)
        unicode_labels.append(codepoint)

    np.savez(os.path.join(data_dir, 'test.npz'),
             font_labels=np.array(font_labels),
             char_labels=np.array(char_labels),
             style_images=np.array(content_images),  # 避免 train_manager 依赖
             content_images=np.array(content_images),
             unicode_labels=np.array(unicode_labels),
             num_original_samples=np.array(len(font_labels)))
    return os.path.join(data_dir, 'test.npz')


if __name__ == '__main__':
    """命令行入口：python -m utils.import_images <images_dir> <source_font> <output_data_dir>"""
    if len(sys.argv) < 4:
        print("Usage: python -m utils.import_images <images_dir> <source_font.ttf> <output_data_dir>")
        sys.exit(1)
    images_dir = sys.argv[1]
    source_font = sys.argv[2]
    output_data_dir = sys.argv[3]
    invert = '--invert' in sys.argv
    result = assemble_composites(images_dir, source_font, output_data_dir, invert=invert)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result['char_count'] > 0:
        write_test_npz(output_data_dir, source_font)
        print("test.npz 已生成")
