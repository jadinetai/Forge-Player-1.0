@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher not found. Install Python 3 from python.org.
  pause
  exit /b 1
)
py forge.py init
start "Forge Player local server" cmd /k "py forge.py serve"
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8765/"
endlocal
