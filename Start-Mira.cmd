@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Mira's Python environment is missing.
  echo Expected: %CD%\.venv\Scripts\python.exe
  pause
  exit /b 1
)

".venv\Scripts\python.exe" -m mira.desktop
if errorlevel 1 (
  echo.
  echo Mira stopped because of the error shown above.
  pause
  exit /b 1
)
