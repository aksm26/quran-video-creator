@echo off
rem Starts Quran Video Creator on Windows. Double-click it, or run it from a terminal.
rem The first run creates .venv and installs what the app needs (Python 3.10+ and internet required).
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo First-time setup: creating the virtual environment...
    py -3 -m venv .venv 2>nul || python -m venv .venv || goto failed
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto failed
)
".venv\Scripts\python.exe" main.py %*
exit /b %errorlevel%

:failed
rem Remove a half-made environment, so the next start tries again from scratch.
if exist .venv rmdir /s /q .venv
echo Setup failed. Install Python 3.10 or newer from https://www.python.org and check your internet connection.
pause
exit /b 1
