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

:: Create local .env on first run without committing secrets to GitHub
if not exist ".env" (
    echo  [SETUP] .env not found - starting first-time setup...
    call "%~dp0setup_env.bat"
    if errorlevel 1 (
        echo.
        echo  [ERROR] First-time setup failed.
        pause
        exit /b 1
    )
    echo.
)

:: Read selected Ollama model from .env, fallback to repo default
set "AI_MODEL=qwen2.5:7b"
set "AI_KEEP_ALIVE=2m"
set "RISK_REVIEW=False"
set "RISK_MODEL=deepseek-r1:8b"
if exist ".env" (
    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
        if /I "%%A"=="OLLAMA_MODEL" set "AI_MODEL=%%B"
        if /I "%%A"=="OLLAMA_KEEP_ALIVE" set "AI_KEEP_ALIVE=%%B"
        if /I "%%A"=="ENABLE_RISK_REVIEW" set "RISK_REVIEW=%%B"
        if /I "%%A"=="OLLAMA_RISK_MODEL" set "RISK_MODEL=%%B"
    )
)

:: Step 1: Start Ollama in background if not already running
echo  [1/5] Checking Ollama...
where ollama >NUL 2>&1
if errorlevel 1 (
    echo.
    echo  [ERROR] Ollama command not found. Please install Ollama first.
    pause
    exit /b 1
)
tasklist /FI "IMAGENAME eq ollama.exe" 2>NUL | find /I "ollama.exe" >NUL
if errorlevel 1 (
    echo        Ollama not running - starting now...
    :: Set env vars BEFORE starting Ollama so the server reads them
    set OLLAMA_KEEP_ALIVE=30m
    set OLLAMA_MAX_LOADED_MODELS=1
    start /MIN "" ollama serve
    echo        Waiting for Ollama API to be ready...
    timeout /t 12 /nobreak >NUL
    
    :: Verify Ollama is responding
    curl -s http://localhost:11434/api/tags >NUL 2>&1
    if errorlevel 1 (
        echo        Still waiting... giving Ollama more time...
        timeout /t 10 /nobreak >NUL
    )
    echo        Ollama started.
) else (
    echo        Ollama already running. OK.
)

:: Step 2: Pull and warm up the selected Ollama model
echo  [2/5] Loading Ollama model: %AI_MODEL%
ollama show "%AI_MODEL%" >NUL 2>&1
if errorlevel 1 (
    echo        Model not found locally - pulling %AI_MODEL%...
    ollama pull "%AI_MODEL%"
    if errorlevel 1 (
        echo.
        echo  [ERROR] Failed to pull Ollama model: %AI_MODEL%
        pause
        exit /b 1
    )
)

set "OLLAMA_KEEP_ALIVE=%AI_KEEP_ALIVE%"
ollama run "%AI_MODEL%" "Reply with OK only." >NUL 2>&1
if errorlevel 1 (
    echo.
    echo  [ERROR] Failed to start Ollama model: %AI_MODEL%
    pause
    exit /b 1
)
echo        Model %AI_MODEL% is ready. Idle unload after %AI_KEEP_ALIVE%. OK.

if /I "%RISK_REVIEW%"=="True" (
    echo        Risk review enabled. Checking on-demand model: %RISK_MODEL%
    ollama show "%RISK_MODEL%" >NUL 2>&1
    if errorlevel 1 (
        echo        Risk model not found locally - pulling %RISK_MODEL%...
        ollama pull "%RISK_MODEL%"
        if errorlevel 1 (
            echo.
            echo  [ERROR] Failed to pull Ollama risk model: %RISK_MODEL%
            pause
            exit /b 1
        )
    )
    echo        Risk model %RISK_MODEL% is available on-demand. OK.
)

:: Step 3: Check Python
echo  [3/5] Checking Python...
python --version >NUL 2>&1
if errorlevel 1 (
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
