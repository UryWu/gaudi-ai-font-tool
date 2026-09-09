@echo off
chcp 65001 >nul
title 停止 AI字体生产工具
echo 正在停止 AI字体生产工具 (端口 7550)...
echo.

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":7550" ^| findstr "LISTENING"') do (
    echo 终止 PID %%a (监听 7550) ...
    taskkill /F /T /PID %%a >nul 2>&1
)

echo 兜底: 清理残留 app.py python 进程...
for /f "tokens=2" %%p in ('wmic process where "name='python.exe' and commandline like '%%app.py%%' and commandline like '%%gaudi-ai-font-tool%%'" get processid 2^>nul ^| findstr /r "[0-9]"') do (
    echo 终止残留 python PID %%p ...
    taskkill /F /T /PID %%p >nul 2>&1
)

echo.
echo 检查端口 7550 是否释放...
set FOUND=0
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":7550" ^| findstr "LISTENING"') do set FOUND=1
if "%FOUND%"=="1" (
    echo [警告] 端口 7550 仍有进程监听！
) else (
    echo [OK] 端口 7550 已释放。
)
pause
