@echo off
chcp 65001 >nul
title TensorBoard - AI字体训练曲线
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tensorboard.ps1" %*
