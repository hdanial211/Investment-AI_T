@echo off
title AI Trading Bot - Enable Dual AI
cd /d "%~dp0"

echo.
echo  ============================================================
echo    AI TRADING BOT - ENABLE DUAL AI ON-DEMAND
echo  ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0enable_dual_ai.ps1"
if errorlevel 1 (
    echo.
    echo  [ERROR] Failed to enable dual AI mode.
    pause
    exit /b 1
)

echo.
echo  Dual AI on-demand mode is ready.
echo.
pause
