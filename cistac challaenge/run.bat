@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
    echo Python was not found. Install Python 3.11 or newer, then try again.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating the project environment...
    py -m venv .venv
    if errorlevel 1 goto :error
)

echo Installing or updating project requirements...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo.
echo Starting AI4Brain. Open http://127.0.0.1:5000 in your browser.
echo Keep this window open while using the app. Press Ctrl+C to stop it.
".venv\Scripts\python.exe" react.py
if errorlevel 1 goto :error
exit /b 0

:error
echo.
echo AI4Brain could not start. Check the message above and confirm Python 3.11 or newer is installed.
pause
exit /b 1
