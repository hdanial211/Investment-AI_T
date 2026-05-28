@echo off
title Investment-AI_T - Start
cd /d "%~dp0"

echo ============================================================
echo   1. MENDAPATKAN UPDATE TERBARU (GIT PULL)
echo ============================================================
git pull
echo.

if not exist "%~dp0Bot Engine\start_bot.bat" (
    echo.
    echo  [ERROR] Internal launcher not found:
    echo          %~dp0Bot Engine\start_bot.bat
    echo.
    echo  Please make sure the Bot Engine folder is still beside this file.
    echo.
    pause
    exit /b 1
)

echo ============================================================
echo   2. MEMULAKAN BOT ENGINE (MICROSERVICES)
echo ============================================================
call start_microservices.bat
exit /b %ERRORLEVEL%