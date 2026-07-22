@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "LOCAL_PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
set "BUNDLED_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
set "PROJECT_PYTHON=%~dp0.build_runtime\pytest-env\Scripts\python.exe"
set "PYTHON_EXE="
if exist "%PROJECT_PYTHON%" (
  "%PROJECT_PYTHON%" -c "import PyInstaller" >nul 2>nul
  if not errorlevel 1 set "PYTHON_EXE=%PROJECT_PYTHON%"
)
if not defined PYTHON_EXE if exist "%LOCAL_PYTHON%" (
  "%LOCAL_PYTHON%" -c "import PyInstaller" >nul 2>nul
  if not errorlevel 1 set "PYTHON_EXE=%LOCAL_PYTHON%"
)
if not defined PYTHON_EXE if exist "%BUNDLED_PYTHON%" set "PYTHON_EXE=%BUNDLED_PYTHON%"
if not defined PYTHON_EXE set "PYTHON_EXE=python"
for %%I in ("%PYTHON_EXE%") do set "PYTHON_HOME=%%~dpI"

"%PYTHON_EXE%" -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --windowed ^
  --onedir ^
  --name "iMileReportAssistant" ^
  --hidden-import app_workflows ^
  --hidden-import wecom_downloader ^
  --hidden-import lark_mail_downloader ^
  --hidden-import imile_dc_downloader ^
  --hidden-import imile_dispatcher ^
  --hidden-import pywinauto ^
  --hidden-import pywinauto.controls.uiawrapper ^
  --hidden-import win32gui ^
  --hidden-import win32clipboard ^
  --hidden-import rapidocr ^
  --collect-data rapidocr ^
  --hidden-import onnxruntime ^
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
if exist "wecom_download_config.json" copy /Y "wecom_download_config.json" "dist\iMileReportAssistant\" >nul
copy /Y "BOT_SETUP.md" "dist\iMileReportAssistant\" >nul
if not exist "dist\iMileReportAssistant\output" mkdir "dist\iMileReportAssistant\output"

echo.
echo Done: dist\iMileReportAssistant\iMileReportAssistant.exe
