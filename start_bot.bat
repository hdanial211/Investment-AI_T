@echo off
title Investment-AI_T — Bot Manager
cd /d "%~dp0"

echo ============================================================
echo   Investment-AI_T — Decoupled Architecture
echo   1 Analyzer + N Executors (Auto-Managed)
echo ============================================================
echo.

echo [1/2] Mendapatkan update terbaru...
git pull 2>nul
echo.

echo [2/2] Memulakan Bot Manager...
echo   - Master Analyzer (Otak)
echo   - Executor Bots (Tangan — satu per akaun)
echo   - Auto-restart jika crash
echo.
echo ============================================================
echo   Tekan Ctrl+C untuk hentikan semua bot.
echo ============================================================
echo.

python bot_manager.py

pause