@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if not exist "lark_config.json" (
  echo 错误：找不到 lark_config.json，无法生成零配置便携版。
  exit /b 1
)

set "LOCAL_PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
set "BUNDLED_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
set "PROJECT_PYTHON=%~dp0.build_runtime\pytest-env\Scripts\python.exe"
set "PYTHON_EXE="
if exist "%PROJECT_PYTHON%" set "PYTHON_EXE=%PROJECT_PYTHON%"
if not defined PYTHON_EXE if exist "%LOCAL_PYTHON%" set "PYTHON_EXE=%LOCAL_PYTHON%"
if not defined PYTHON_EXE if exist "%BUNDLED_PYTHON%" set "PYTHON_EXE=%BUNDLED_PYTHON%"
if not defined PYTHON_EXE set "PYTHON_EXE=python"

call "build_windows_app.bat"
if errorlevel 1 exit /b %errorlevel%

set "RELEASE_DIR=dist\iMileReportAssistant"
set "ZIP_PATH=dist\iMileReportAssistant-portable.zip"

"%PYTHON_EXE%" "build_portable_config.py" ^
  --source "lark_config.json" ^
  --output "%RELEASE_DIR%\lark_config.json"
if errorlevel 1 exit /b %errorlevel%

if exist "%RELEASE_DIR%\wecom_download_config.json" del /Q "%RELEASE_DIR%\wecom_download_config.json"
copy /Y "PORTABLE_README.md" "%RELEASE_DIR%\" >nul
if not exist "%RELEASE_DIR%\input" mkdir "%RELEASE_DIR%\input"
if not exist "%RELEASE_DIR%\output" mkdir "%RELEASE_DIR%\output"

powershell.exe -NoProfile -Command ^
  "Compress-Archive -LiteralPath '%CD%\%RELEASE_DIR%' -DestinationPath '%CD%\%ZIP_PATH%' -CompressionLevel Optimal -Force"
if errorlevel 1 (
  echo 错误：便携版 ZIP 生成失败。
  exit /b %errorlevel%
)

echo.
echo 便携版已生成：%ZIP_PATH%
echo 仅限公司内部可信同事使用，请勿公开分发。
