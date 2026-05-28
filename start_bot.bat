@echo off
title Investment-AI_T - Start
cd /d "%~dp0"

echo ============================================================
echo   1. MENDAPATKAN UPDATE TERBARU (GIT PULL)
echo ============================================================
git pull
echo.

echo ============================================================
echo   2. MEMULAKAN DESKTOP COMMAND CENTER
echo ============================================================
start /B pythonw desktop_launcher.py
exit /b 0