@echo off
setlocal
cd /d "%~dp0"

set "LOCAL_PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
set "BUNDLED_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
set "PYTHON_EXE="

if not exist "%LOCAL_PYTHON%" goto try_bundled
"%LOCAL_PYTHON%" -c "import pandas; import openpyxl; import xlrd" >nul 2>nul
if errorlevel 1 goto try_bundled
set "PYTHON_EXE=%LOCAL_PYTHON%"
goto run_script

:try_bundled
if not exist "%BUNDLED_PYTHON%" goto try_path
"%BUNDLED_PYTHON%" -c "import pandas; import openpyxl; import xlrd" >nul 2>nul
if errorlevel 1 goto try_path
set "PYTHON_EXE=%BUNDLED_PYTHON%"
goto run_script

:try_path
python -c "import pandas; import openpyxl; import xlrd" >nul 2>nul
if errorlevel 1 goto missing_python
set "PYTHON_EXE=python"
goto run_script

:missing_python
echo Python with pandas, openpyxl, and xlrd was not found.
echo Run: python -m pip install -r requirements.txt
set "EXIT_CODE=1"
goto finish

:run_script
echo Extracting tracking numbers from the input folder...
"%PYTHON_EXE%" "%~dp0getTrakingNum.py"
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%EXIT_CODE%"=="0" goto failed
goto finish

:failed
echo Extraction failed. See the error above.

:finish
exit /b %EXIT_CODE%
