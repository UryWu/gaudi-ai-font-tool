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
  - 训练产物：<outputDir>/train_images_<时间戳>/
  - 批次内日志：<批次>/.logs/train_<时间戳>.log（引擎原始）
               <批次>/.logs/summary_<时间戳>.log（本脚本汇总）

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


_log_buffer = []  # 日志文件尚未创建时先缓存，创建后一次性补写


def log(msg, log_file=None):
    """同时输出到控制台和日志文件（文件未就绪时先进缓冲区）"""
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    if log_file:
        log_file.write(line + "\n")
        log_file.flush()
    else:
        _log_buffer.append(line)


def _flush_buffer(log_file):
    """把缓冲的早期日志补写进日志文件"""
    for line in _log_buffer:
        log_file.write(line + "\n")
    log_file.flush()
    _log_buffer.clear()


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

    # 续训入口：config.jsonc 的 resumeFrom 非空 = 续训模式（跳过 prepare，复用其所在批次）
    # 专用字段，与 UI/生成页使用的 lastCheckpoint 解耦，避免「想新建却误续训」
    resume_from = cfg.get("resumeFrom", "").strip()
    add_epochs = int(cfg.get("continueEpochs", 50))  # 续训追加轮次（epochs <= ckpt epoch 时生效）

    log("=" * 70)
    log("个人字库 LoRA 训练任务" + ("（续训模式）" if resume_from else ""))
    log("=" * 70)
    log(f"配置文件:    {CONFIG_PATH}")
    log(f"baseCheckpoint: {paths['baseCheckpoint']}")
    log(f"sourceFont:     {paths['sourceFont']}")
    log(f"refFont:        {ref_font or '(空, images_dir 模式)'}")
    log(f"imagesDir:      {images_dir or '(空)'}")
    log(f"outputDir:      {output_dir}")
    log("")
    log(f"epochs={epochs}, batch_size={batch_size}, lora_r={lora_r}, lora_alpha={lora_alpha}")
    log(f"cfg={cfg_scale}, num_fonts={num_fonts}, num_chars={num_chars}")
    log(f"max_chars_per_font={max_chars_per_font}, num_workers={num_workers}")
    log(f"char_count={char_count}  (None=全部, 数字=取前 N 字)")
    if resume_from:
        log(f"续训入口:       {resume_from}")
        log(f"continueEpochs: {add_epochs}  (在已训轮次基础上追加这么多轮)")

    # import train_manager 单例
    sys.path.insert(0, str(PROJECT_ROOT))
    from utils.train_manager import train_manager

    if resume_from:
        # ===== 续训模式：跳过 prepare，直接复用 checkpoint 所在批次 =====
        ckpt_path = Path(resume_from)
        if not ckpt_path.is_file():
            sys.exit(f"错误: 续训 checkpoint 不存在: {resume_from}")
        data_dir = str(ckpt_path.parent)
        test_npz = os.path.join(data_dir, "test.npz")
        font_dir = os.path.join(data_dir, "001_font")
        if not os.path.isdir(font_dir):
            sys.exit(f"错误: 批次数据不完整（缺 001_font）: {font_dir}")
        if not os.path.isfile(test_npz):
            sys.exit(f"错误: 批次数据不完整（缺 test.npz）: {test_npz}")

        char_count_real = len([f for f in os.listdir(font_dir) if f.endswith(".png")])
        skipped = 0

        # 读 checkpoint 已训轮次 → 目标总轮次 = 已训 + continueEpochs
        try:
            import torch
            _ck = torch.load(resume_from, map_location="cpu", weights_only=False)
            ckpt_epoch = int(_ck.get("epoch", -1))
            del _ck
        except Exception as e:
            sys.exit(f"错误: 读取 checkpoint 失败: {e}")
        if ckpt_epoch < 0:
            sys.exit("错误: checkpoint 无 epoch 信息，无法续训")
        target_epochs = ckpt_epoch + 1 + add_epochs

        log("")
        log("[Step 1] 续训模式：跳过数据准备，复用已有批次")
        log(f"  已训轮次:    {ckpt_epoch + 1} (0..{ckpt_epoch})")
        log(f"  本次追加:    {add_epochs} 轮 (continueEpochs)")
        log(f"  目标总轮次:  {target_epochs}")
    else:
        # 引导：images_dir 模式要求 images_dir
        if not images_dir:
            sys.exit("错误: imagesDir 为空，但本脚本走 images_dir 模式。编辑 config.jsonc 的 imagesDir 字段。")
        if not Path(images_dir).is_dir():
            sys.exit(f"错误: imagesDir 目录不存在: {images_dir}")

        # Step 1: prepare_data_from_images
        log("")
        log("[Step 1] 准备训练数据（images_dir 模式）...")
        prep_result = train_manager.prepare_data_from_images(
            output_dir=output_dir,
            images_dir=images_dir,
            source_font=paths["sourceFont"],
            char_count=char_count,
        )
        if not prep_result.get("success"):
            sys.exit(f"准备失败: {prep_result.get('error')}")

        data_dir = prep_result["data_dir"]
        test_npz = prep_result.get("test_npz")
        char_count_real = prep_result.get("char_count", 0)
        skipped = prep_result.get("skipped", 0)
        target_epochs = epochs  # 新建训练：epochs 即目标总轮次

    # 批次日志目录（所有训练日志统一进这里，带时间戳）
    ts_now = time.strftime("%Y%m%d_%H%M%S")
    batch_logs_dir = Path(data_dir) / ".logs"
    batch_logs_dir.mkdir(parents=True, exist_ok=True)
    summary_log_path = batch_logs_dir / f"summary_{ts_now}.log"
    log_file = open(summary_log_path, "w", encoding="utf-8")
    _flush_buffer(log_file)  # 补写前面缓存的头部信息
    log(f"批次目录: {data_dir}", log_file)
    log(f"汇总日志: {summary_log_path}", log_file)
    log("", log_file)
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
        "epochs": target_epochs,
        "batch_size": batch_size,
        "lora_r": lora_r,
        "lora_alpha": lora_alpha,
        "cfg": cfg_scale,
        "num_fonts": num_fonts,
        "num_chars": num_chars,
        "max_chars_per_font": max_chars_per_font,
        "num_workers": num_workers,
        # 每轮都存 LoRA checkpoint，中断后最多丢 1 epoch
        "save_last_freq": int(cfg.get("saveLastFreq", 1)),
        # 续训：target_epochs 已算好，这里传 add_epochs 仅供 train_manager 兜底
        "add_epochs": add_epochs,
    }
    start_result = train_manager.start_training(start_params)
    if not start_result.get("success"):
        log(f"启动失败: {start_result.get('error')}", log_file)
        sys.exit(1)

    log("  训练已启动（subprocess 跑引擎）", log_file)
    log(f"  引擎日志: {train_manager.get_status().get('log_path', '(未生成)')}", log_file)

    # Step 3: 轮询状态 + 引擎 batch 进度
    log("", log_file)
    log("[Step 3] 轮询训练状态（每 10 秒）...", log_file)

    # 引擎日志路径由 train_manager 生成（<批次>/.logs/train_<ts>.log），从 status 读取
    engine_log_path = train_manager.get_status().get("log_path") or ""
    last_engine_lines = 0  # 跟踪已打印行数，避免重复

    train_t0 = time.time()  # 训练计时
    last_status = None      # 检测状态变化

    while True:
        time.sleep(10)
        status = train_manager.get_status()
        ts = time.strftime("%H:%M:%S")

        # 状态行：epoch / loss / lr + 进度条 + 预估剩余
        cur_epoch = status["epoch"]
        total_epoch = status["total_epochs"] or target_epochs
        elapsed_train = time.time() - train_t0
        if cur_epoch > 0 and total_epoch > 0:
            pct = cur_epoch / total_epoch
            bar_w = 20
            filled = int(bar_w * pct)
            bar = "█" * filled + "░" * (bar_w - filled)
            eta_sec = elapsed_train * (1 - pct) / pct
            eta_str = f"{eta_sec/60:.1f}min" if eta_sec > 60 else f"{eta_sec:.0f}s"
            progress = f" [{bar}] {pct*100:5.1f}% 已用 {elapsed_train/60:.1f}min 估剩 {eta_str}"
        else:
            progress = f" 启动中... (已用 {elapsed_train/60:.1f}min)"

        line = f"[{ts}] {status['status']:9s} epoch={cur_epoch:>3}/{total_epoch:<3} loss={status['loss']:.4f} lr={status['lr']:.2e}{progress}"
        print(line, flush=True)
        log_file.write(line + "\n")
        log_file.flush()

        # 状态变更时打印
        if status["status"] != last_status:
            log(f"  >>> 状态变更: {last_status} → {status['status']}", log_file)
            last_status = status["status"]

        # 引擎训练日志 tail（只打新行，含 batch 进度如 [3/80]）
        if os.path.isfile(engine_log_path):
            try:
                with open(engine_log_path, "r", encoding="utf-8", errors="replace") as f:
                    all_lines = f.readlines()
                if len(all_lines) > last_engine_lines:
                    for line in all_lines[last_engine_lines:]:
                        # 过滤 bf16/future 警告噪声，保留 Epoch / loss / data / checkpoint
                        if any(k in line for k in ("Epoch:", "data:", "loss:", "Done!", "Total time", "checkpoint", "base lr", "Loaded")):
                            ts_short = ts[3:]  # 简略时间
                            engine_line = f"  │ [{ts_short}] {line.rstrip()}"
                            print(engine_line, flush=True)
                            log_file.write(engine_line + "\n")
                            log_file.flush()
                    last_engine_lines = len(all_lines)
            except Exception as e:
                pass

        if status["status"] in ("completed", "error", "idle") and cur_epoch >= target_epochs:
            break
        if status["status"] == "error":
            log(f"  训练错误: {status.get('error', '未知错误')}", log_file)
            break

    # 完成总结
    overall_elapsed = time.time() - overall_t0
    status = train_manager.get_status()
    log("", log_file)
    log("=" * 70, log_file)
    log("完成！", log_file)
    log(f"  最终状态:     {status['status']}", log_file)
    log(f"  批次目录:     {data_dir}", log_file)
    log(f"  checkpoint:   {data_dir}/checkpoint-last.pth", log_file)
    log(f"  引擎日志:     {engine_log_path}", log_file)
    log(f"  汇总日志:     {summary_log_path}", log_file)
    log(f"  最终 epoch:   {status['epoch']}/{status['total_epochs']}", log_file)
    log(f"  最终 loss:    {status['loss']}", log_file)
    log(f"  总用时:       {overall_elapsed:.1f}s ({overall_elapsed/60:.1f}min)", log_file)
    log("=" * 70, log_file)
    log_file.close()


if __name__ == "__main__":
    main()
