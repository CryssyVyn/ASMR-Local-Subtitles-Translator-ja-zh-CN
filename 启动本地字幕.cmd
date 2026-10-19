@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
 echo 本地运行环境缺失，请先完成安装。
 pause
 exit /b 1
)
if not exist "models\asmr-zh-cn-q4_k_m.gguf" (
 echo ASMR 中文模型还没有下载完成。请运行“继续下载模型.cmd”。
 pause
 exit /b 1
)
if not exist "models\whisper-small\model.bin" (
 echo 日语识别模型尚未就绪。请运行“继续下载模型.cmd”。
 pause
 exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "app.py"
