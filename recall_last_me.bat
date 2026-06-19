@echo off
setlocal

"C:\Users\11799\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" "%~dp0send_lark_images.py" --recall-last --send-as user
if errorlevel 1 (
  echo.
  echo Recall last message failed. See the error above.
  exit /b %errorlevel%
)
