@echo off
title AI Trading Bot - First-Time Setup
cd /d "%~dp0"

set "BOT_DIR=%~dp0..\Bot Engine"

echo.
echo  ============================================================
echo    AI TRADING BOT - FIRST-TIME ENV SETUP
echo  ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_env.ps1" -TargetDir "%BOT_DIR%"
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  [ERROR] Failed to create .env
    pause
    exit /b 1
)

echo.
echo  Setup complete.
echo.
