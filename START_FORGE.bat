@echo off
cd /d "%~dp0"
if exist "%LOCALAPPDATA%\Python\bin\python.exe" (
  "%LOCALAPPDATA%\Python\bin\python.exe" launch.py
) else (
  py -3 launch.py
)
if errorlevel 1 pause
