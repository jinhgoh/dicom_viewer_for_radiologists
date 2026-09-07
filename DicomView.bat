@echo off
rem Launch DicomView on the study folder that contains this project.
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found on the PATH.
    echo Install Python 3.10 or newer, then run:  pip install -r requirements.txt
    pause
    exit /b 1
)

python -c "import pydicom, numpy, PyQt6" >nul 2>nul
if errorlevel 1 (
    echo Installing the required libraries, one moment...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Installation failed. Run this by hand:  pip install -r requirements.txt
        pause
        exit /b 1
    )
)

start "" pythonw viewer.py %*
