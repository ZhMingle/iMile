@echo off
setlocal

set COUNT=%~1
if "%COUNT%"=="" set COUNT=1

set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

%PYTHON_EXE% "%~dp0send_lark_images.py" --recall-last %COUNT% --send-as user
if errorlevel 1 (
  echo.
  echo Recall messages failed. See the error above.
  exit /b %errorlevel%
)
