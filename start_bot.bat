@echo off
title Investment-AI_T V4 — Cloud-Native System Starter
cd /d "%~dp0"

echo ============================================================
echo   Investment-AI_T V4 — 100%% Cloud-Native Hybrid
echo   Booting All Systems (Bot, Dashboard)...
echo ============================================================
echo.

echo [1/5] Mendapatkan update terbaru dari GitHub...
git pull 2>nul
echo.

echo [2/5] Membuka Terminal MT5 (Master dan Individu)...
python "Bot Engine\launch_terminals.py"
echo.

echo [3/4] Memulakan Papan Pemuka Visual (Next.js)...
start "Dashboard Next.js" cmd /k "cd frontend-dashboard && npm run dev"
echo Papan Pemuka sedang dilancarkan. (Akan tersedia di http://localhost:3000)
echo.

echo [4/4] Memulakan Bot Manager...
echo   - Membaca market dan menghantar signal ke Supabase
echo   - Menilai (Evaluate) Active Trades secara live
echo.
echo ============================================================
echo   Biarkan tetingkap ini terbuka. Tutup tetingkap untuk berhenti.
echo ============================================================
echo.

python bot_manager.py

pause