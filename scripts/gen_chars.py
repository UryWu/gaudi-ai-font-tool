# -*- coding: utf-8 -*-
"""
个人字库生成脚本（独立运行，无需 Flask）

用法：
  编辑下面 CONFIG 区的配置，然后：
    python scripts/gen_chars.py

依赖：
  - 训练好的 checkpoint（默认 model/run/train_images_20260910_031118/checkpoint-last.pth）
  - 基本字库 TTF（默认 font/default.ttf）
  - zi2zi-JiT 引擎源码（G:\\Projects\\projects_ai\\zi2zi-JiT）
  - Python 环境需装 torch + torchvision + Pillow + numpy + einops + opencv-python + peft + safetensors + timm + scipy + torch-fidelity

输出：
  - PNG 字形图：<输出目录>/gen_<时间戳>/uniXXXX_字.png 或 uXXXXX_字.png
  - 详细日志：<输出目录>/.logs/gen_<时间戳>.log（同时输出到控制台）

支持：
  - 单字 / 多字 / 整段文本（含空白、标点）
  - 字数多时自动 multipler 多采样
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


# ============================================================================
# CONFIG 区（修改这里调整，所有设置都在这里）
# ============================================================================

# —— 模型位置（个人字迹训练产出的 checkpoint）——
CHECKPOINT = r"G:\Projects\projects_ai\gaudi-ai-font-tool\model\run\train_images_20260910_160142\checkpoint-last.pth"

# —— REF_FONT（基本字库） vs SOURCE_FONT（源字体） ——
# REF_FONT    = 引擎画 ref 网格（8 个"风格参考字"）时用的字体
#              = 引擎学习"你的字长啥样"的目标
#              = 应当填**你的个人字库 TTF**（从 gaudi-font-preprocess 导出的字形图合成的 TTF）
#              = 临时没合成 TTF 时可暂用 default.ttf（但 default.ttf 字形不全，会跳过大量字）
# SOURCE_FONT = 引擎画 source 通道（"要生成哪个 unicode 码点"的标准字形）时用的字体
#              = 引擎认字用，必须是字形数据齐全的字体
#              = 推荐 simsunb.ttf（宋体扩展 B，3.4 万字）或 msyh.ttc（微软雅黑，3 万+字）
#              = 不要用 default.ttf（只有约 1000 个稀疏 CJK 实际字形，常用字渲染成空白被跳过）
REF_FONT    = r"G:\Projects\projects_ai\gaudi-ai-font-tool\font\my_personal_font.ttf"  # 个人字库（152 字）
SOURCE_FONT = r"G:\Projects\projects_ai\gaudi-ai-font-tool\font\default.ttf"            # 源字体

# —— 输入文本（三选一：优先 INPUT_TEXT_STDIN > INPUT_TEXT_FILE > INPUT_TEXT）——
# INPUT_TEXT = "你好，世界！这是一个测试段落。     段首缩进用空格保留。"
INPUT_TEXT = "你"
INPUT_TEXT_FILE = ""          # 留空 = 不读文件
INPUT_TEXT_STDIN = False      # True 时从 stdin 读

# —— 输出位置（落在 model/run/ 下，与训练产出 train_images_<ts>/ 并列；脚本会再新建 gen_<ts>/ 子目录）——
OUTPUT_DIR = r"G:\Projects\projects_ai\gaudi-ai-font-tool\model\run"

# —— 生成参数 ——
MULTIPLIER = 5          # 每字生成张数（多采样便于人工筛选）
CFG = 4.0               # classifier-free guidance
BATCH_SIZE = 4           # GTX 1060 6GB 推荐 ≤4
RESOLUTION = 256         # 复合图左 1/4 source 通道尺寸
REF_SIZE = 128           # ref 网格单字尺寸

# —— 引擎位置 ——
ENGINE_DIR = r"G:\Projects\projects_ai\zi2zi-JiT"
PYTHON_EXE = r"G:\Projects\projects_ai\gaudi-ai-font-tool\.venv\Scripts\python.exe"

# ============================================================================
# 逻辑
# ============================================================================

def log(msg, log_file=None):
    """同时输出到控制台和日志文件"""
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    if log_file:
        log_file.write(line + "\n")
        log_file.flush()


def get_text() -> str:
    """按优先级：INPUT_TEXT_STDIN > INPUT_TEXT_FILE > INPUT_TEXT"""
    if INPUT_TEXT_STDIN:
        return sys.stdin.read()
    if INPUT_TEXT_FILE:
        with open(INPUT_TEXT_FILE, "r", encoding="utf-8") as f:
            return f.read()
    return INPUT_TEXT


def extract_chars(text: str) -> list:
    """提取要生成的字符：保留所有可见字，跳过空白（段首缩进会被丢弃——引擎 npz 不支持空格）"""
    return [ch for ch in text if ch.strip()]


def build_npz(chars, ref_font, source_font, npz_path, log_file):
    """构造引擎所需的 npz（content=渲染、style=「永」参考）"""
    import numpy as np
    from PIL import Image
    from fontTools.ttLib import TTFont

    sys.path.insert(0, ENGINE_DIR)
    from data_processing.font_utils import GlyphRenderer

    src_r = GlyphRenderer(source_font, RESOLUTION)
    ref_r = GlyphRenderer(ref_font, REF_SIZE)

    src_tt = TTFont(source_font, fontNumber=0) if source_font.lower().endswith('.ttc') else TTFont(source_font)
    src_cmap = src_tt.getBestCmap() or {}
    src_tt.close()

    font_labels, char_labels, content_images, style_images, unicode_labels = [], [], [], [], []

    # ref 网格 = 风格参考，必须用 REF_FONT（个人字库）渲染「永」才有你的笔迹风格
    yong = ref_r.render(ord('永'))
    if yong is None or np.array(yong).mean() > 250:
        log("  ⚠ REF_FONT 渲染「永」失败/空白，fallback 到 SOURCE_FONT（风格参考将不准确）", log_file)
        yong = src_r.render(ord('永'))
    if yong is None:
        raise RuntimeError(f"SOURCE_FONT 也无法渲染「永」（ref 网格兜底必需）")
    ref_arr = np.array(yong.resize((REF_SIZE, REF_SIZE), Image.Resampling.LANCZOS)).transpose(2, 0, 1)

    skipped = []
    for ch in chars:
        cp = ord(ch)
        if cp not in src_cmap:
            skipped.append(ch)
            continue
        try:
            src_img = src_r.render(cp)
            if src_img is None:
                skipped.append(ch)
                continue
            src_arr = np.array(src_img.resize((RESOLUTION, RESOLUTION), Image.Resampling.LANCZOS))
            if src_arr.mean() > 250:  # 空白字过滤
                skipped.append(ch)
                continue
            src_arr = src_arr.transpose(2, 0, 1)
            font_labels.append(0)
            char_labels.append(0)
            style_images.append(ref_arr.copy())
            content_images.append(src_arr)
            unicode_labels.append(cp)
        except Exception as e:
            log(f"  跳过 {ch!r} (U+{cp:04X}): {e}", log_file)
            skipped.append(ch)

    if skipped:
        log(f"源字体不支持 {len(skipped)} 个字（已跳过）: {''.join(skipped[:20])}", log_file)
    if not font_labels:
        raise RuntimeError("所有字符源字体均无法渲染，任务终止")

    np.savez(npz_path,
             font_labels=np.array(font_labels),
             char_labels=np.array(char_labels),
             style_images=np.stack(style_images),
             content_images=np.stack(content_images),
             unicode_labels=np.array(unicode_labels),
             num_original_samples=np.array(len(font_labels)))
    return len(font_labels), len(skipped)


def run_engine(checkpoint, npz_path, output_dir, num_images, cfg, batch_size, log_file):
    """调用 zi2zi-JiT 引擎"""
    cmd = [
        PYTHON_EXE,
        os.path.join(ENGINE_DIR, "generate_chars.py"),
        "--checkpoint", checkpoint,
        "--test_npz", npz_path,
        "--output_dir", output_dir,
        "--sampling_method", "heun",
        "--num_sampling_steps", "50",
        "--cfg", str(cfg),
        "--batch_size", str(batch_size),
        "--num_images", str(num_images),
    ]
    log(f"调用引擎: {' '.join(cmd)}", log_file)
    log(f"  cwd: {ENGINE_DIR}", log_file)

    t0 = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=ENGINE_DIR)
    out, err = proc.communicate(timeout=1800)
    elapsed = time.time() - t0
    rc = proc.returncode
    log(f"引擎退出码: {rc}, 用时: {elapsed:.1f}s", log_file)

    if rc != 0:
        log(f"  stdout 末尾: {out.decode('utf-8', errors='replace')[-400:]}", log_file)
        log(f"  stderr 末尾: {err.decode('utf-8', errors='replace')[-400:]}", log_file)
        raise RuntimeError(f"引擎退出码 {rc}")
    return elapsed


def find_engine_output(work_dir):
    """递归找引擎生成的 PNG"""
    pngs = []
    for root, _, files in os.walk(work_dir):
        for f in files:
            if f.endswith(".png"):
                pngs.append(os.path.join(root, f))
    return pngs


def main():
    # 路径校验
    if not os.path.isfile(CHECKPOINT):
        sys.exit(f"checkpoint 不存在: {CHECKPOINT}")
    if not os.path.isfile(REF_FONT):
        sys.exit(f"ref_font 不存在: {REF_FONT}")
    if not os.path.isfile(SOURCE_FONT):
        sys.exit(f"source_font 不存在: {SOURCE_FONT}")

    output_root = Path(OUTPUT_DIR)
    output_root.mkdir(parents=True, exist_ok=True)
    logs_dir = output_root / ".logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    actual_output = output_root / f"gen_{timestamp}"
    actual_output.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"gen_{timestamp}.log"
    log_file = open(log_path, "w", encoding="utf-8")

    overall_t0 = time.time()
    log("=" * 70, log_file)
    log("个人字库生成任务", log_file)
    log("=" * 70, log_file)
    log(f"模型位置:    {CHECKPOINT}", log_file)
    log(f"基本字库:    {REF_FONT}", log_file)
    log(f"源字体:      {SOURCE_FONT}", log_file)
    log(f"输出位置:    {output_root}", log_file)
    log(f"输出子目录:  {actual_output}", log_file)
    log(f"日志文件:    {log_path}", log_file)
    log(f"引擎:        {ENGINE_DIR}", log_file)
    log(f"Python:      {PYTHON_EXE}", log_file)

    raw_text = get_text()
    chars = extract_chars(raw_text)
    log(f"输入文本长度: {len(raw_text)} 字符, 去空白后 {len(chars)} 字待生成", log_file)
    log(f"待生成字符: {''.join(chars[:30])}{'...' if len(chars) > 30 else ''}", log_file)

    if not chars:
        log("没有需要生成的字符，退出", log_file)
        log_file.close()
        return

    success_codes = set()
    total_engine_time = 0.0
    work_dir = tempfile.mkdtemp(prefix="gen_script_")
    try:
        t0 = time.time()
        expanded = chars * MULTIPLIER
        npz_path = os.path.join(work_dir, "pending.npz")
        num_samples, skipped = build_npz(expanded, REF_FONT, SOURCE_FONT, npz_path, log_file)
        log(f"建 npz 用时: {time.time()-t0:.2f}s, 样本数={num_samples}（{len(chars)} 字 × {MULTIPLIER} 倍）", log_file)

        engine_t = run_engine(CHECKPOINT, npz_path, work_dir, num_samples, CFG, BATCH_SIZE, log_file)
        total_engine_time += engine_t

        png_files = find_engine_output(work_dir)
        log(f"引擎产出 {len(png_files)} 张 PNG", log_file)

        pat = re.compile(r'(?:uni|u|U\+)([0-9A-Fa-f]+)')
        round_success = 0
        for png in png_files:
            m = pat.search(png)
            if not m:
                continue
            code = int(m.group(1), 16)
            if code in success_codes:
                continue
            fname = f"u{code:05X}_{chr(code)}.png" if code > 0xFFFF else f"uni{code:04X}_{chr(code)}.png"
            shutil.copy(png, actual_output / fname)
            success_codes.add(code)
            round_success += 1

        log(f"本轮新增 {round_success} 字", log_file)
        log(f"累计成功 {len(success_codes)}/{len(chars)}", log_file)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    overall_elapsed = time.time() - overall_t0
    log("=" * 70, log_file)
    log("完成！", log_file)
    log(f"  生成目录: {actual_output}", log_file)
    log(f"  成功:     {len(success_codes)}/{len(chars)} 字", log_file)
    log(f"  引擎用时: {total_engine_time:.1f}s", log_file)
    log(f"  总用时:   {overall_elapsed:.1f}s", log_file)
    log(f"  日志:     {log_path}", log_file)
    log_file.close()


if __name__ == "__main__":
    main()
