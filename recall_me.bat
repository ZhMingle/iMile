@echo off
setlocal

set COUNT=%~1
if "%COUNT%"=="" set COUNT=1

"C:\Users\11799\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" "%~dp0send_lark_images.py" --recall-last %COUNT% --send-as user
if errorlevel 1 (
  echo.
  echo Recall messages failed. See the error above.
  exit /b %errorlevel%
)
