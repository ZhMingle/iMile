@echo off
setlocal

set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

echo.
echo == Update workbook ==
%PYTHON_EXE% "%~dp0update_report_data.py"
if errorlevel 1 (
  echo.
  echo Update workbook failed. See the error above.
  exit /b %errorlevel%
)

echo.
echo == Build message pack ==
%PYTHON_EXE% "%~dp0build_message_pack.py"
if errorlevel 1 (
  echo.
  echo Build message pack failed. See the error above.
  exit /b %errorlevel%
)

echo.
echo == Update latest user message batch ==
%PYTHON_EXE% "%~dp0send_lark_images.py" --update-latest-batch --send-as user
if errorlevel 1 (
  echo.
  echo Update latest user message batch failed. See the error above.
  exit /b %errorlevel%
)
