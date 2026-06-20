@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=pythonw"

start "" "%PYTHON_EXE%" "%~dp0imile_report_win32.py"

