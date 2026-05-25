@echo off
title AI Trading Bot - Launcher
color 0A
cls

echo.
echo  ============================================================
echo    GOLD AI TRADING BOT - STARTUP
echo  ============================================================
echo.

:: Set working directory to this script's folder
cd /d "%~dp0"

:: If an older install still has .env beside the root wrapper, reuse it.
if not exist ".env" if exist "%~dp0..\.env" (
    echo  [SETUP] Found existing .env beside root start_bot.bat - copying into Bot Engine...
    copy "%~dp0..\.env" ".env" >NUL
)

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

:: Read cloud AI settings from .env
set "AI_PROVIDER=openrouter"
set "AI_FALLBACK_PROVIDER=huggingface"
set "AI_MAIN_MODEL=openai/gpt-oss-20b:free"
set "AI_RISK_MODEL=openai/gpt-oss-120b:free"
set "ENABLE_RISK_REVIEW=True"
set "OPENROUTER_API_KEY="
set "HF_TOKEN="

if exist ".env" (
    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
        if /I "%%A"=="AI_PROVIDER" set "AI_PROVIDER=%%~B"
        if /I "%%A"=="AI_FALLBACK_PROVIDER" set "AI_FALLBACK_PROVIDER=%%~B"
        if /I "%%A"=="AI_MAIN_MODEL" set "AI_MAIN_MODEL=%%~B"
        if /I "%%A"=="AI_RISK_MODEL" set "AI_RISK_MODEL=%%~B"
        if /I "%%A"=="ENABLE_RISK_REVIEW" set "ENABLE_RISK_REVIEW=%%~B"
        if /I "%%A"=="OPENROUTER_API_KEY" set "OPENROUTER_API_KEY=%%~B"
        if /I "%%A"=="HF_TOKEN" set "HF_TOKEN=%%~B"
    )
)

:: Step 1: Validate cloud AI config. No model warm-up needed.
echo  [1/5] Checking cloud AI config...
if /I "%AI_PROVIDER%"=="openrouter" (
    if "%OPENROUTER_API_KEY%"=="" (
        echo.
        echo  [ERROR] OPENROUTER_API_KEY missing in Bot Engine\.env
        echo          Run Setup\setup_env.bat or edit Bot Engine\.env locally.
        pause
        exit /b 1
    )
    if /I "%OPENROUTER_API_KEY%"=="CHANGE_ME" (
        echo.
        echo  [ERROR] OPENROUTER_API_KEY still set to CHANGE_ME.
        pause
        exit /b 1
    )
)

if /I "%AI_PROVIDER%"=="huggingface" (
    if "%HF_TOKEN%"=="" (
        echo.
        echo  [ERROR] HF_TOKEN missing in Bot Engine\.env
        pause
        exit /b 1
    )
    if /I "%HF_TOKEN%"=="CHANGE_ME" (
        echo.
        echo  [ERROR] HF_TOKEN still set to CHANGE_ME.
        pause
        exit /b 1
    )
)

echo        Provider: %AI_PROVIDER%
echo        Main model: %AI_MAIN_MODEL%
if /I "%ENABLE_RISK_REVIEW%"=="True" echo        Risk model: %AI_RISK_MODEL%
echo        Cloud AI config OK.

:: Step 2: Check Python
echo  [2/5] Checking Python...
python --version >NUL 2>&1
if errorlevel 1 (
    echo.
    echo  [ERROR] Python not found. Please install Python 3.10+
    echo          and make sure it is added to PATH.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo        %%v found. OK.

:: Step 3: Check/install Python packages
echo  [3/5] Checking Python packages...
python -c "import requests, pandas, numpy, dotenv, loguru, MetaTrader5" >NUL 2>&1
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

:: Step 4: Launch the trading bot engine in background
echo  [4/5] Starting AI Trading Bot Engine...
start /MIN "" python main.py
timeout /t 3 /nobreak >NUL

:: Step 5: Launch the TUI dashboard in foreground
echo  [5/5] Starting Terminal UI Dashboard...
echo.
echo  ============================================================
echo    Bot is LIVE. Close this window to STOP the dashboard.
echo    (You may need to close the background python window to stop the engine)
echo  ============================================================
echo.

python dashboard.py

:: Bot exited
echo.
echo  ============================================================
echo    Bot has stopped. Press any key to close.
echo  ============================================================
pause >NUL
