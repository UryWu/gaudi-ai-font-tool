# -*- coding: utf-8 -*-
# AI 字体生产工具 - PowerShell 停止脚本
# 杀死所有占用 7550 端口的 Flask 进程（含整个进程树，避免残留孤儿）
# 用法：powershell -ExecutionPolicy Bypass -File stop-ai-font-port-7550.ps1

$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$PORT = 7550
$killed = @()

function Kill-Tree($processId) {
    # 注意：参数不能叫 $pid（$PID 是 PowerShell 内置自动变量）
    $out = cmd /c "taskkill /F /T /PID $processId" 2>&1
    $out | ForEach-Object { Write-Host "  $_" }
}

# 1) 找占用 7550 的所有进程（LISTENING + ESTABLISHED 都算，防 TIME_WAIT 残余）
Write-Host "扫描端口 ${PORT} 上所有监听进程..."
$lines = netstat -ano | Select-String "TCP.*:${PORT}.*LISTENING"
if (-not $lines) {
    Write-Host "端口 ${PORT} 上没有 LISTENING 进程，可能已停止。" -ForegroundColor Yellow
} else {
    $pids = $lines | ForEach-Object {
        ($_ -split '\s+')[-1] | Where-Object { $_ -match '^\d+$' }
    } | Sort-Object -Unique

    foreach ($procId in $pids) {
        Write-Host "发现 PID $procId 监听 ${PORT}，终止进程树..."
        Kill-Tree $procId
        $killed += $procId
    }
}

# 2) 兜底：清理任何残留的 app.py python 进程（可能是孤儿）
Write-Host ""
Write-Host "兜底扫描残留 app.py python 进程..."
$stray = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*app.py*' -and $_.CommandLine -like '*gaudi-ai-font-tool*' }
foreach ($p in $stray) {
    if ($pids -notcontains $p.ProcessId) {
        Write-Host "终止残留 python PID $($p.ProcessId) ..."
        Kill-Tree $p.ProcessId
        $killed += $p.ProcessId
    }
}

# 3) 验证
Write-Host ""
Start-Sleep -Milliseconds 500
$left = netstat -ano | Select-String "TCP.*:${PORT}.*LISTENING"
if ($left) {
    Write-Host "警告：端口 ${PORT} 仍有进程监听：" -ForegroundColor Red
    $left | ForEach-Object { Write-Host "  $_" }
    exit 1
} else {
    Write-Host "端口 ${PORT} 已释放。" -ForegroundColor Green
    if ($killed.Count -gt 0) {
        Write-Host "已终止 $($killed.Count) 个进程树。" -ForegroundColor Green
    }
    exit 0
}
