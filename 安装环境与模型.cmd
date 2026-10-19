@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
if errorlevel 1 (
 echo 安装尚未完成。请根据上面的提示处理，然后重新运行本文件。
) else (
 echo 已完成当前安装步骤。
)
pause
