@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Chua co moi truong. Hay chay setup.ps1 truoc.
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "app.py"
