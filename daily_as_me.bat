@echo off
setlocal

"C:\Users\11799\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" "%~dp0run_daily_report.py" --send-as user
if errorlevel 1 (
  echo.
  echo Daily report as me failed. See the error above.
  exit /b %errorlevel%
)
