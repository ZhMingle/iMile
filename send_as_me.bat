@echo off
setlocal

"C:\Users\11799\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" "%~dp0send_lark_images.py" --send --send-as user
if errorlevel 1 (
  echo.
  echo Send as me failed. See the error above.
  exit /b %errorlevel%
)
