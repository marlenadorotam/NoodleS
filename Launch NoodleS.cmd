@echo off
setlocal
if not exist "%~dp0.venv\Scripts\pythonw.exe" (
    echo Python environment not found. Run "Install NoodleS.cmd" first.
    pause
    exit /b 1
)
start "" /D "%~dp0" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0NoodleS.pyw"
