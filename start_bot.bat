@echo off
title Investment-AI_T V4 — Cloud-Native Bot Manager
cd /d "%~dp0"

echo ============================================================
echo   Investment-AI_T V4 — 100%% Cloud-Native Hybrid
echo   Master Analyzer (Otak AI) - Supabase DB
echo ============================================================
echo.

echo [1/3] Mendapatkan update terbaru dari GitHub...
git pull 2>nul
echo.

echo [2/3] Membuka Terminal MT5 (Master dan Individu)...
python "Bot Engine\launch_terminals.py"
echo.

echo "[3/3] Memulakan Master Analyzer..."
echo   - Membaca market dan menghantar signal ke Supabase
echo   - Menilai (Evaluate) Active Trades setiap 10 minit
echo   - (Executor / MT5 berjalan berasingan di terminal klien)
echo.
echo ============================================================
echo   Tekan Ctrl+C untuk hentikan Master Analyzer.
echo ============================================================
echo.

python bot_manager.py

pause