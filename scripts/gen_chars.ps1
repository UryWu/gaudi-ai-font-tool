# -*- coding: utf-8 -*-
# 个人字库生成脚本 - PowerShell 启动器
# 内部直接调 python scripts/gen_chars.py（不启 Flask）
# 用法：在项目根 PowerShell 里运行
#   powershell -ExecutionPolicy Bypass -File scripts\gen-chars.ps1

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir\..

Write-Host "AI 字体生成（个人字库）" -ForegroundColor Cyan
Write-Host ("=" * 60) -ForegroundColor Cyan
Write-Host ""
Write-Host "配置文件: scripts\gen_chars.py 顶部的 CONFIG 区" -ForegroundColor Yellow
Write-Host "  - CHECKPOINT  训练好的模型路径"
Write-Host "  - REF_FONT     基本字库 TTF"
Write-Host "  - SOURCE_FONT  源字体 TTF"
Write-Host "  - INPUT_TEXT   要生成的文本（支持整段、空白、段首缩进）"
Write-Host "  - OUTPUT_DIR   生成图存放位置"
Write-Host "  - MULTIPLIER   每字生成张数（多采样便于人工筛选）"
Write-Host ""
Write-Host "日志: <OUTPUT_DIR>\.logs\gen_<时间戳>.log"
Write-Host ""

# 直接调 Python 脚本（不依赖 Flask）
& ".\.venv\Scripts\python.exe" "scripts\gen_chars.py"
exit $LASTEXITCODE
