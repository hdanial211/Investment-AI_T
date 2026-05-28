@echo off
title Investment-AI_T — One-Click Launcher
color 0A
cls

echo.
echo  ============================================================
echo    INVESTMENT-AI_T  ^|  ONE-CLICK SYSTEM LAUNCHER
echo  ============================================================
echo.

cd /d "%~dp0"

:: ── STEP 1: Update from GitHub ──────────────────────────────────
echo  [1/4] Mendapatkan update terbaru (git pull)...
git pull
echo.

:: ── STEP 2: Start Desktop Command Center (background) ───────────
echo  [2/4] Memulakan Desktop Command Center...
if exist "%~dp0desktop_launcher.py" (
    start "Desktop Command Center" /B pythonw desktop_launcher.py
    echo        Desktop Command Center started.
) else (
    echo        [SKIP] desktop_launcher.py tidak dijumpai.
)
echo.

:: ── STEP 3: Start AI Trader (Terminal 1) ────────────────────────
echo  [3/4] Memulakan AI Trader (main.py)...
if exist "%~dp0Bot Engine\start_bot.bat" (
    start "AI Trader [Terminal 1]" cmd /k "cd /d ""%~dp0Bot Engine"" && python main.py"
    timeout /t 5 /nobreak >nul
    echo        AI Trader started.
) else (
    echo        [ERROR] Bot Engine\start_bot.bat tidak dijumpai.
)
echo.

:: ── STEP 4: Start Active Trade Manager (Terminal 3) ─────────────
echo  [4/4] Memulakan Active Trade Manager (terminal_trade_manager.py)...
if exist "%~dp0Bot Engine\terminal_trade_manager.py" (
    start "Trade Manager [Terminal 3]" cmd /k "cd /d ""%~dp0Bot Engine"" && python terminal_trade_manager.py"
    echo        Trade Manager started.
) else (
    echo        [SKIP] terminal_trade_manager.py tidak dijumpai.
)
echo.

echo  ============================================================
echo    Semua sistem telah dilancarkan!
echo    Boleh tutup tetingkap launcher ini sekarang.
echo  ============================================================
echo.
timeout /t 5 /nobreak >nul
exit /b 0