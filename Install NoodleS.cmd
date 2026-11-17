@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    py -3.12 --version >nul 2>&1
    if errorlevel 1 (
        python -c "import sys; sys.exit(sys.version_info[:2] != (3, 12))"
        if errorlevel 1 (
            echo Install Python 3.12 for Windows and try again.
            goto failed
        )
        python -m venv .venv
    ) else (
        py -3.12 -m venv .venv
    )
    if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -m ensurepip --upgrade
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m noodles.install_bridge %*
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m noodles.install_file_association
if errorlevel 1 goto failed
echo Ready. Run "Launch NoodleS.cmd".
pause
exit /b 0
:failed
echo Unable to set up NoodleS. Check the message above.
pause
exit /b 1
