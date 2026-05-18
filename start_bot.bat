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

:: Read selected Ollama model from .env, fallback to repo default
set "AI_MODEL=qwen2.5:7b"
if exist ".env" (
    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
        if /I "%%A"=="OLLAMA_MODEL" set "AI_MODEL=%%B"
    )
)

:: Step 1: Start Ollama in background if not already running
echo  [1/5] Checking Ollama...
where ollama >NUL 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  [ERROR] Ollama command not found. Please install Ollama first.
    pause
    exit /b 1
)
tasklist /FI "IMAGENAME eq ollama.exe" 2>NUL | find /I "ollama.exe" >NUL
if %ERRORLEVEL% NEQ 0 (
    echo        Ollama not running - starting now...
    start /MIN "" ollama serve
    echo        Waiting for Ollama to be ready...
    timeout /t 8 /nobreak >NUL
    echo        Ollama started.
) else (
    echo        Ollama already running. OK.
)

:: Step 2: Pull and warm up the selected Ollama model
echo  [2/5] Loading Ollama model: %AI_MODEL%
ollama show "%AI_MODEL%" >NUL 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo        Model not found locally - pulling %AI_MODEL%...
    ollama pull "%AI_MODEL%"
    if %ERRORLEVEL% NEQ 0 (
        echo.
        echo  [ERROR] Failed to pull Ollama model: %AI_MODEL%
        pause
        exit /b 1
    )
)

set "OLLAMA_KEEP_ALIVE=30m"
ollama run "%AI_MODEL%" "Reply with OK only." >NUL 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  [ERROR] Failed to start Ollama model: %AI_MODEL%
    pause
    exit /b 1
)
echo        Model %AI_MODEL% is loaded and ready. OK.

:: Step 3: Check Python
echo  [3/5] Checking Python...
python --version >NUL 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  [ERROR] Python not found. Please install Python 3.10+
    echo          and make sure it is added to PATH.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo        %%v found. OK.

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
