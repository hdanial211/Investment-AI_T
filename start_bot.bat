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
echo   2. MEMBUKA WEB DASHBOARD
echo ============================================================
echo Starting Local Web Server pada port 5500...
start /MIN cmd /c "python -m http.server 5500"
timeout /t 2 /nobreak >NUL

echo Membuka browser ke Web Dashboard...
start http://127.0.0.1:5500/Dashboard/index.html
echo.

echo ============================================================
echo   3. MEMULAKAN BOT ENGINE
echo ============================================================
call "%~dp0Bot Engine\start_bot.bat"
exit /b %ERRORLEVEL%