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
echo  [1/3] Checking Ollama...
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
echo  [2/3] Checking Python...
python --version >NUL 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  [ERROR] Python not found. Please install Python 3.10+
    echo          and make sure it is added to PATH.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo        %%v found. OK.

:: ── Step 3: Launch the trading bot ───────────────────────────────────────────
echo  [3/3] Starting AI Trading Bot...
echo.
echo  ============================================================
echo    Bot is LIVE. Close this window to STOP the bot.
echo  ============================================================
echo.

python main.py

:: ── Bot exited ────────────────────────────────────────────────────────────────
echo.
echo  ============================================================
echo    Bot has stopped. Press any key to close.
echo  ============================================================
pause >NUL
