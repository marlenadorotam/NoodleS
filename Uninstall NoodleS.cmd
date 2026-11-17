@echo off
setlocal
cd /d "%~dp0"
py -3.12 --version >nul 2>&1
if errorlevel 1 (
    python -m noodles.uninstall %*
) else (
    py -3.12 -m noodles.uninstall %*
)
if errorlevel 1 goto failed
pause
exit /b 0
:failed
echo Unable to uninstall NoodleS. Check the message above.
pause
exit /b 1
