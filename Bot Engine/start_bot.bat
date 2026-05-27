@echo off
title AI Trading Bot - Engine
color 0A
cls

echo.
echo  ============================================================
echo    GOLD AI TRADING BOT - ENGINE
echo  ============================================================
echo.

:: Set working directory to this script's folder
cd /d "%~dp0"

:: Create local .env on first run without committing secrets to GitHub
if not exist ".env" (
    echo  [SETUP] .env not found - starting first-time setup...
    call "%~dp0..\Setup\setup_env.bat"
    if errorlevel 1 (
        echo.
        echo  [ERROR] First-time setup failed.
        pause
        exit /b 1
    )
    echo.
)

:: Step 1: Check Python
echo  [1/3] Checking Python...
python --version >NUL 2>&1
if errorlevel 1 (
    echo.
    echo  [WARNING] Python not found! Starting automatic download and installation...
    echo            Please DO NOT close this window. It may take 1-3 minutes.
    echo.
    powershell -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.10.11/python-3.10.11-amd64.exe' -OutFile 'python_installer.exe'"
    echo  [INFO] Installing Python 3.10 silently (with PATH enabled)...
    start /wait python_installer.exe /quiet InstallAllUsers=0 PrependPath=1 Include_test=0
    del python_installer.exe
    echo.
    echo  [SUCCESS] Python has been installed successfully!
    echo            Please CLOSE this black terminal and click start_bot.bat again.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo        %%v found. OK.

:: Step 2: Check/install Python packages
echo  [2/3] Checking Python packages...
python -c "import requests, pandas, numpy, dotenv, loguru, textual, rich, MetaTrader5" >NUL 2>&1
if errorlevel 1 (
    echo        Missing packages detected - installing from Setup\requirements.txt...
    python -m pip install -r "%~dp0..\Setup\requirements.txt"
    if errorlevel 1 (
        echo.
        echo  [ERROR] Failed to install Python packages.
        pause
        exit /b 1
    )
)
echo        Python packages OK.

:: Step 3: Launch the trading bot engine
echo  [3/3] Starting AI Trading Bot Engine...
echo.
cd /d "%~dp0"
python main.py

:: Bot exited
echo.
echo  ============================================================
echo    Bot has stopped. Press any key to close.
echo  ============================================================
pause >NUL
