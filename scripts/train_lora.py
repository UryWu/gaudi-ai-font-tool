# -*- coding: utf-8 -*-
"""
个人字库训练脚本（独立运行，无需 Flask）

所有配置从项目根的 config.jsonc 读：
  - 路径（checkpoint/sourceFont/refFont/imagesDir/outputDir/lastCheckpoint）
  - 训练超参（epochs/batchSize/loraR/loraAlpha/cfg/numFonts/numChars/...）
  - 取字数量（charCountMode + charCountCustom）

用法：
  1. 编辑 config.jsonc 配置（路径 + 训练超参）
  2. python scripts/train_lora.py

输出：
  - 训练产物：<outputDir>/train_images_<时间戳>/（含 001_font/*.png + test.npz + checkpoint-last.pth）
  - 详细日志：<outputDir>/<batch_dir>/.logs/training.log（同时实时回显到控制台）

依赖：
  - config.jsonc（项目根）
  - json5 库（uv pip install json5）
  - 引擎 + Python 环境（与 app.py / gen_chars.py 一致）
"""

import json5
import os
import shutil
import sys
import time
from pathlib import Path


# ============================================================================
# CONFIG 加载
# ============================================================================

PROJECT_ROOT = Path(r"G:\Projects\projects_ai\gaudi-ai-font-tool")
CONFIG_PATH = PROJECT_ROOT / "config.jsonc"
LOGS_DIR_RELATIVE = ".logs"  # 批次目录下日志子目录（点前缀，引擎扫描跳过）


def load_config() -> dict:
    """从 config.jsonc 读所有训练配置"""
    if not CONFIG_PATH.is_file():
        sys.exit(f"config.jsonc 不存在: {CONFIG_PATH}")
    raw = CONFIG_PATH.read_text(encoding="utf-8").strip()
    if not raw:
        sys.exit(f"config.jsonc 为空: {CONFIG_PATH}")
    try:
        return json5.loads(raw)
    except Exception as e:
        sys.exit(f"config.jsonc 解析失败: {e}")


def log(msg, log_file=None):
    """同时输出到控制台和日志文件"""
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    if log_file:
        log_file.write(line + "\n")
        log_file.flush()


def build_char_count(cfg: dict):
    """根据 charCountMode 解析 char_count 实际值"""
    mode = cfg.get("charCountMode", "all")
    if mode == "all":
        return None  # 用全部
    if mode == "custom":
        return int(cfg.get("charCountCustom", 1000))
    # mode 可能是 "800" / "3000" 字符串
    try:
        return int(mode)
    except (ValueError, TypeError):
        return None


def setup_paths(cfg: dict):
    """校验路径"""
    paths = {
        "baseCheckpoint": cfg.get("baseCheckpoint", ""),
        "sourceFont": cfg.get("sourceFont", ""),
        "refFont": cfg.get("refFont", ""),
        "imagesDir": cfg.get("imagesDir", ""),
        "outputDir": cfg.get("outputDir", str(PROJECT_ROOT / "model" / "run")),
    }
    errors = []
    if not paths["baseCheckpoint"] or not Path(paths["baseCheckpoint"]).is_file():
        errors.append(f"baseCheckpoint 缺失或不存在: {paths['baseCheckpoint']}")
    if not paths["sourceFont"] or not Path(paths["sourceFont"]).is_file():
        errors.append(f"sourceFont 缺失或不存在: {paths['sourceFont']}")
    if not paths["outputDir"]:
        errors.append("outputDir 缺失")
    if errors:
        sys.exit("配置错误:\n  - " + "\n  - ".join(errors))
    return paths


def main():
    overall_t0 = time.time()
    cfg = load_config()
    paths = setup_paths(cfg)

    # 训练超参
    epochs = int(cfg.get("epochs", 50))
    batch_size = int(cfg.get("batchSize", 4))
    lora_r = int(cfg.get("loraR", 32))
    lora_alpha = int(cfg.get("loraAlpha", 32))
    cfg_scale = float(cfg.get("cfg", 2.6))
    num_fonts = int(cfg.get("numFonts", 1000))
    num_chars = int(cfg.get("numChars", 200000))
    max_chars_per_font = int(cfg.get("maxCharsPerFont", 10000))
    num_workers = int(cfg.get("numWorkers", 0))
    char_count = build_char_count(cfg)

    images_dir = paths["imagesDir"].strip()
    ref_font = paths["refFont"].strip()

    # 输出目录
    output_dir = paths["outputDir"]

    # 输出批次（prepare_data_from_images 自己会建 train_images_<ts> 子目录）
    # 我们提前算 prepare 之后的路径便于日志定位
    ts_now = time.strftime("%Y%m%d_%H%M%S")
    expected_batch_dir = os.path.join(output_dir, f"train_images_{ts_now}")

    # 准备批次日志（先建批次目录不可能，只能在 prepare 后知道）
    # 这里把总日志写到 <outputDir>/.logs/train_<ts>.log（更稳妥）
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    logs_root = output_root / ".logs"
    logs_root.mkdir(parents=True, exist_ok=True)
    summary_log_path = logs_root / f"train_{ts_now}.log"
    log_file = open(summary_log_path, "w", encoding="utf-8")

    log("=" * 70, log_file)
    log("个人字库 LoRA 训练任务", log_file)
    log("=" * 70, log_file)
    log(f"配置文件:    {CONFIG_PATH}", log_file)
    log(f"baseCheckpoint: {paths['baseCheckpoint']}", log_file)
    log(f"sourceFont:     {paths['sourceFont']}", log_file)
    log(f"refFont:        {ref_font or '(空, images_dir 模式)'}", log_file)
    log(f"imagesDir:      {images_dir or '(空)'}", log_file)
    log(f"outputDir:      {output_dir}", log_file)
    log(f"预期批次:      {expected_batch_dir}/", log_file)
    log(f"批次日志:      <批次>/.logs/training.log", log_file)
    log(f"本脚本汇总:    {summary_log_path}", log_file)
    log(f"", log_file)
    log(f"epochs={epochs}, batch_size={batch_size}, lora_r={lora_r}, lora_alpha={lora_alpha}", log_file)
    log(f"cfg={cfg_scale}, num_fonts={num_fonts}, num_chars={num_chars}", log_file)
    log(f"max_chars_per_font={max_chars_per_font}, num_workers={num_workers}", log_file)
    log(f"char_count={char_count}  (None=全部, 数字=取前 N 字)", log_file)

    # 引导：images_dir 模式要求 images_dir
    if not images_dir:
        sys.exit("错误: imagesDir 为空，但本脚本走 images_dir 模式。编辑 config.jsonc 的 imagesDir 字段。")
    if not Path(images_dir).is_dir():
        sys.exit(f"错误: imagesDir 目录不存在: {images_dir}")

    # import train_manager 单例
    sys.path.insert(0, str(PROJECT_ROOT))
    from utils.train_manager import train_manager

    # Step 1: prepare_data_from_images
    log("", log_file)
    log("[Step 1] 准备训练数据（images_dir 模式）...", log_file)
    prep_result = train_manager.prepare_data_from_images(
        output_dir=output_dir,
        images_dir=images_dir,
        source_font=paths["sourceFont"],
        char_count=char_count,
    )
    if not prep_result.get("success"):
        log(f"准备失败: {prep_result.get('error')}", log_file)
        sys.exit(1)

    data_dir = prep_result["data_dir"]
    test_npz = prep_result.get("test_npz")
    char_count_real = prep_result.get("char_count", 0)
    skipped = prep_result.get("skipped", 0)
    log(f"  数据目录:    {data_dir}", log_file)
    log(f"  实际字数:    {char_count_real} (请求 {char_count})", log_file)
    log(f"  test.npz:    {test_npz}", log_file)
    log(f"  跳过字符:    {skipped} 个（源字体不支持）", log_file)

    # Step 2: start_training
    log("", log_file)
    log("[Step 2] 启动训练...", log_file)
    start_params = {
        "output_dir": data_dir,
        "data_path": data_dir,
        "test_npz_path": test_npz,
        "base_checkpoint": paths["baseCheckpoint"],
        "source_font": paths["sourceFont"],
        "epochs": epochs,
        "batch_size": batch_size,
        "lora_r": lora_r,
        "lora_alpha": lora_alpha,
        "cfg": cfg_scale,
        "num_fonts": num_fonts,
        "num_chars": num_chars,
        "max_chars_per_font": max_chars_per_font,
        "num_workers": num_workers,
    }
    start_result = train_manager.start_training(start_params)
    if not start_result.get("success"):
        log(f"启动失败: {start_result.get('error')}", log_file)
        sys.exit(1)

    log("  训练已启动（subprocess 跑引擎）", log_file)

    # Step 3: 轮询状态
    log("", log_file)
    log("[Step 3] 轮询训练状态（每 10 秒）...", log_file)
    import urllib.request
    while True:
        time.sleep(10)
        status = train_manager.get_status()
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] status={status['status']} epoch={status['epoch']}/{status['total_epochs']} loss={status['loss']} lr={status['lr']}"
        print(line, flush=True)
        log_file.write(line + "\n")
        log_file.flush()

        if status["status"] in ("completed", "error", "idle") and status["epoch"] >= epochs:
            break
        if status["status"] == "error":
            log(f"  训练错误: {status['error_message']}", log_file)
            break

    # 完成总结
    overall_elapsed = time.time() - overall_t0
    status = train_manager.get_status()
    log("", log_file)
    log("=" * 70, log_file)
    log("完成！", log_file)
    log(f"  最终状态:     {status['status']}", log_file)
    log(f"  数据目录:     {data_dir}", log_file)
    log(f"  checkpoint:   {data_dir}/checkpoint-last.pth", log_file)
    log(f"  批次训练日志: {data_dir}/.logs/training.log", log_file)
    log(f"  本次汇总日志: {summary_log_path}", log_file)
    log(f"  最终 epoch:   {status['epoch']}/{status['total_epochs']}", log_file)
    log(f"  最终 loss:    {status['loss']}", log_file)
    log(f"  总用时:       {overall_elapsed:.1f}s ({overall_elapsed/60:.1f}min)", log_file)
    log("=" * 70, log_file)
    log_file.close()


if __name__ == "__main__":
    main()
