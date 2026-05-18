@echo off
title 🤖 AI Trading Bot — Launcher
color 0A
cls

echo.
echo  ============================================================
echo    GOLD AI TRADING BOT — STARTUP
echo  ============================================================
echo.

:: ── Set working directory to this script's folder ────────────────────────────
cd /d "%~dp0"

:: ── Step 1: Start Ollama in background if not already running ────────────────
echo  [1/4] Checking Ollama...
tasklist /FI "IMAGENAME eq ollama.exe" 2>NUL | find /I "ollama.exe" >NUL
if %ERRORLEVEL% NEQ 0 (
    echo        Ollama not running — starting now...
    start /MIN "" ollama serve
    echo        Waiting for Ollama to be ready...
    timeout /t 8 /nobreak >NUL
    echo        Ollama started.
) else (
    echo        Ollama already running. OK.
)

:: ── Step 2: Check Python ─────────────────────────────────────────────────────
echo  [2/4] Checking Python...
python --version >NUL 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  [ERROR] Python not found. Please install Python 3.10+
    echo          and make sure it is added to PATH.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo        %%v found. OK.

:: ── Step 3: Launch the trading bot (Engine) in background ──────────────
echo  [3/4] Starting AI Trading Bot Engine...
start /MIN "" python main.py
timeout /t 3 /nobreak >NUL

:: ── Step 4: Launch the TUI Dashboard (Foreground) ──────────────────────
echo  [4/4] Starting Terminal UI Dashboard...
echo.
echo  ============================================================
echo    Bot is LIVE. Close this window to STOP the dashboard.
echo    (You may need to close the background python window to stop the engine)
echo  ============================================================
echo.

python dashboard.py

:: ── Bot exited ────────────────────────────────────────────────────────────────
echo.
echo  ============================================================
echo    Bot has stopped. Press any key to close.
echo  ============================================================
pause >NUL
