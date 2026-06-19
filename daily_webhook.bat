@echo off
setlocal

set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

%PYTHON_EXE% "%~dp0run_daily_report.py" --send-as webhook
if errorlevel 1 (
  echo.
  echo Daily webhook report failed. See the error above.
  exit /b %errorlevel%
)
