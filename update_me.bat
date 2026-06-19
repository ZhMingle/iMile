@echo off
setlocal

set MESSAGE_ID=%~1
set IMAGE_PATH=%~2
if "%MESSAGE_ID%"=="" (
  echo Usage: update_me.bat MESSAGE_ID IMAGE_PATH
  exit /b 1
)
if "%IMAGE_PATH%"=="" (
  echo Usage: update_me.bat MESSAGE_ID IMAGE_PATH
  exit /b 1
)

set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

%PYTHON_EXE% "%~dp0send_lark_images.py" --update-message "%MESSAGE_ID%" --image "%IMAGE_PATH%" --send-as user
if errorlevel 1 (
  echo.
  echo Update message failed. See the error above.
  exit /b %errorlevel%
)
