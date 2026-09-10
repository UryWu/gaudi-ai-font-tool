# -*- coding: utf-8 -*-
# 个人字库 LoRA 训练 - PowerShell 启动器
# 内部直接调 python scripts/train_lora.py（不启 Flask）
# 用法：在项目根 PowerShell 里运行
#   powershell -ExecutionPolicy Bypass -File scripts\train-lora.ps1

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir\..

Write-Host "AI 字体 LoRA 训练（个人字库）" -ForegroundColor Cyan
Write-Host ("=" * 60) -ForegroundColor Cyan
Write-Host ""
Write-Host "所有配置从 config.jsonc 读取（在项目根）" -ForegroundColor Yellow
Write-Host "  编辑 config.jsonc 后再跑本脚本" -ForegroundColor Yellow
Write-Host ""
Write-Host "关键字段："
Write-Host "  baseCheckpoint  预训练权重"
Write-Host "  imagesDir       字形素材目录（images_dir 模式必填）"
Write-Host "  sourceFont      源字体 TTF"
Write-Host "  outputDir       训练产物根目录"
Write-Host "  epochs          训练轮数"
Write-Host "  batchSize       批大小（1060 6GB 必 ≤4）"
Write-Host "  numFonts        字体数（必 ≥1000）"
Write-Host "  charCountMode   'all'=全部 | 'custom'=用 charCountCustom"
Write-Host ""
Write-Host "日志：<outputDir>\.logs\"
Write-Host "训练日志：<批次目录>\.logs\training.log"
Write-Host ""

# 直接调 Python 脚本（不依赖 Flask）
& ".\.venv\Scripts\python.exe" "scripts\train_lora.py"
exit $LASTEXITCODE
