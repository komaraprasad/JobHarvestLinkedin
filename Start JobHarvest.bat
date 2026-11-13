@echo off
rem One-click start: first run creates a private Python environment (needs internet once), then opens the dashboard.
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
if not exist ".venv\Scripts\python.exe" (
  echo First start: setting up, this takes a minute...
  %PY% -m venv .venv || (echo Python 3.10+ is required: install it from https://www.python.org/downloads/ and tick "Add to PATH". & pause & exit /b 1)
  ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt || (echo Package install failed - check the internet connection. & pause & exit /b 1)
)
".venv\Scripts\python.exe" app.py --open
pause
