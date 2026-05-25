@echo off
title AI Trading Bot - Enable Cloud Dual AI
cd /d "%~dp0"

set "BOT_DIR=%~dp0..\Bot Engine"

echo.
echo  ============================================================
echo    AI TRADING BOT - ENABLE CLOUD DUAL AI
echo  ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0enable_dual_ai.ps1" -TargetDir "%BOT_DIR%"
if errorlevel 1 (
    echo.
    echo  [ERROR] Failed to enable dual AI mode.
    pause
    exit /b 1
)

echo.
echo  Cloud dual AI on-demand mode is ready.
echo.
pause
