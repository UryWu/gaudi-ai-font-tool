# -*- coding: utf-8 -*-
# AI 字体生产工具 - PowerShell 启动脚本
# 与 start-ai-font-port-7550.bat 等价，但 UTF-8 输出更稳，支持从任意目录调用
# 用法：在 PowerShell 里执行 .\start-ai-font-port-7550.ps1

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# 切到脚本所在目录（支持从任意位置调用）
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# 设置窗口标题
$Host.UI.RawUI.WindowTitle = 'AI Font Tool - Port 7550'

Write-Host '正在启动 AI 字体生产工具...'
Write-Host '访问地址: http://localhost:7550'
Write-Host '按 Ctrl+C 停止服务'
Write-Host ''

# 用 uv 启动（uv 会自动管理 .venv，无依赖时自动安装）
try {
    uv run python app.py
}
finally {
    Write-Host ''
    Write-Host '服务已停止。'
    Read-Host '按 Enter 退出'
}