# -*- coding: utf-8 -*-
# TensorBoard 启动脚本 —— 查看训练 loss / lr 曲线
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File scripts\tensorboard.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\tensorboard.ps1 -Batch train_images_20260910_235403
#   powershell -ExecutionPolicy Bypass -File scripts\tensorboard.ps1 -Port 6007 -NoBrowser
#
# 说明：
#   - 默认读取 model\run 下所有批次的 events 文件，每批次一个 run，可横向对比
#   - 训练进行中也能连，曲线实时增长
#   - 按 Ctrl+C 停止

param(
    [string]$LogDir = '',          # 指定批次目录名（相对 model\run）或绝对路径；空=整个 model\run
    [int]$Port = 6006
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# 项目根目录（脚本在 scripts\ 下）
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectRoot

$TbExe = Join-Path $ProjectRoot '.venv\Scripts\tensorboard.exe'
if (-not (Test-Path $TbExe)) {
    Write-Host "[错误] 找不到 tensorboard: $TbExe" -ForegroundColor Red
    Write-Host "       请先安装: uv pip install --python .venv\Scripts\python.exe tensorboard" -ForegroundColor Yellow
    exit 1
}

# 解析 logdir
$RunRoot = Join-Path $ProjectRoot 'model\run'
if ([string]::IsNullOrWhiteSpace($LogDir)) {
    $Target = $RunRoot
} elseif (Test-Path $LogDir) {
    $Target = (Resolve-Path $LogDir).Path        # 传了存在的绝对/相对路径
} else {
    $Target = Join-Path $RunRoot $LogDir         # 传了批次名
}

if (-not (Test-Path $Target)) {
    Write-Host "[错误] 日志目录不存在: $Target" -ForegroundColor Red
    exit 1
}

$EventFiles = Get-ChildItem -Path $Target -Recurse -Filter 'events.out.tfevents.*' -ErrorAction SilentlyContinue
Write-Host "TensorBoard 启动中..." -ForegroundColor Cyan
Write-Host "  项目根:   $ProjectRoot"
Write-Host "  日志目录: $Target"
Write-Host "  事件文件: $($EventFiles.Count) 个"
Write-Host ""
Write-Host "  浏览器打开: http://localhost:$Port" -ForegroundColor Green
Write-Host "  按 Ctrl+C 停止" -ForegroundColor Yellow
Write-Host ""

& $TbExe --logdir $Target --port $Port
