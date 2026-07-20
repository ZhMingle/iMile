@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"
for %%I in ("%PYTHON_EXE%") do set "PYTHON_HOME=%%~dpI"

"%PYTHON_EXE%" -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --windowed ^
  --onedir ^
  --name "iMileReportAssistant" ^
  --hidden-import app_workflows ^
  --hidden-import wecom_downloader ^
  --hidden-import pywinauto ^
  --hidden-import pywinauto.controls.uiawrapper ^
  --hidden-import getTrakingNum ^
  --hidden-import update_report_data ^
  --hidden-import build_message_pack ^
  --hidden-import send_lark_images ^
  --add-data "当日数据统计_20260603_233359_公式版.xlsx;." ^
  --add-data "lark_bot_config.example.json;." ^
  --add-data "wecom_download_config.example.json;." ^
  imile_report_win32.py

if errorlevel 1 (
  echo.
  echo Build failed.
  exit /b %errorlevel%
)

copy /Y "当日数据统计_20260603_233359_公式版.xlsx" "dist\iMileReportAssistant\" >nul
copy /Y "lark_bot_config.example.json" "dist\iMileReportAssistant\" >nul
copy /Y "wecom_download_config.example.json" "dist\iMileReportAssistant\" >nul
copy /Y "BOT_SETUP.md" "dist\iMileReportAssistant\" >nul
if not exist "dist\iMileReportAssistant\output" mkdir "dist\iMileReportAssistant\output"

echo.
echo Done: dist\iMileReportAssistant\iMileReportAssistant.exe
