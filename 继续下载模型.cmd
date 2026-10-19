@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
".venv\Scripts\python.exe" -u setup_runtime.py
if errorlevel 1 (
 echo 下载未完成。已有数据会保留，再次双击本文件可继续。
) else (
 echo 下载完成。可以打开“启动本地字幕.cmd”。
)
pause
