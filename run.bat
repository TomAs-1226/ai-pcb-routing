@echo off
REM AI PCB Designer launcher for Windows
REM
REM Usage:
REM   run.bat              # GUI mode
REM   run.bat --cli        # CLI mode
REM   run.bat --cli --template esp32_carrier

setlocal

set SCRIPT_DIR=%~dp0

REM Try python commands in order
where python3 >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    set PYTHON=python3
) else (
    where python >nul 2>nul
    if %ERRORLEVEL% EQU 0 (
        set PYTHON=python
    ) else (
        echo ERROR: Python not found. Install Python 3.10+ from https://www.python.org/downloads/
        exit /b 1
    )
)

REM Check for PySide6
%PYTHON% -c "import PySide6" >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo Installing PySide6 and dependencies...
    %PYTHON% -m pip install PySide6 numpy shapely
)

REM Check numpy
%PYTHON% -c "import numpy" >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo Installing core dependencies...
    %PYTHON% -m pip install numpy shapely
)

set PYTHONPATH=%SCRIPT_DIR%src;%PYTHONPATH%
%PYTHON% -m ai_pcb_designer %*
