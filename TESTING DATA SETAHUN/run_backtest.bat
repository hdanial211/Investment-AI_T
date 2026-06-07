@echo off
title Investment-AI_T - Backtesting System
cd /d "%~dp0"

echo ============================================================
echo   Investment-AI_T - Backtesting System
echo ============================================================
echo.

REM ── Check Python ────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python tidak ditemui!
    echo Sila pasang Python 3.8+ dari https://python.org
    echo Pastikan tick "Add Python to PATH" semasa install.
    pause
    exit /b 1
)

echo Python found:
python --version
echo.

REM ── Install dependencies satu per satu ──────────────────────
echo ============================================================
echo   Installing dependencies (first time may take 1-2 min)...
echo ============================================================

python -m pip install --upgrade pip --quiet
python -m pip install pandas --quiet
python -m pip install numpy --quiet
python -m pip install yfinance --quiet
python -m pip install requests --quiet
python -m pip install python-dotenv --quiet

echo.
echo Verifying yfinance...
python -c "import yfinance; print('[OK] yfinance', yfinance.__version__)"
if errorlevel 1 (
    echo [ERROR] yfinance gagal dipasang!
    echo Cuba jalankan secara manual: python -m pip install yfinance
    pause
    exit /b 1
)

python -c "import pandas; print('[OK] pandas', pandas.__version__)"
python -c "import numpy; print('[OK] numpy', numpy.__version__)"
echo.

REM ── Mode selection ───────────────────────────────────────────
echo ============================================================
echo   Mode 1: Quick Run (default XAUUSD, All Styles)
echo   Mode 2: Custom Settings - buka backtest_settings.html dulu
echo ============================================================
echo.

REM ── Check if settings file exists ───────────────────────────
set USE_AI_FLAG=

echo ============================================================
echo   [PILIHAN AI]
echo   Adakah awak mahu gunakan REAL AI (Gemini) untuk filter trades?
echo   - YA: Keputusan lebih tepat/realistik tapi akan mengambil masa LEBIH LAMA.
echo   - TIDAK: Hanya gunakan technical indicator (Sangat pantas).
echo ============================================================
set /p use_ai="Guna REAL AI? (Y/N): "
if /I "%use_ai%"=="Y" goto AI_YES
goto AI_NO

:AI_YES
set USE_AI_FLAG=--use-ai
echo [INFO] REAL AI Filter dihidupkan!
goto RUN_SCRIPT

:AI_NO
echo [INFO] AI Filter dimatikan (Fast mode).
goto RUN_SCRIPT

:RUN_SCRIPT
echo.

if exist "backtest_settings.json" goto RUN_CUSTOM
goto RUN_DEFAULT

:RUN_CUSTOM
echo [INFO] Settings file found - menggunakan custom settings...
echo.
python run_backtest.py %USE_AI_FLAG%
goto CHECK_ERROR

:RUN_DEFAULT
echo [INFO] Tiada settings file - menggunakan defaults...
echo [INFO] Symbol: XAUUSD ^| Styles: All ^| Balance: $10,000
echo [INFO] Data: 1 tahun lepas sehingga hari ini (auto-download)
echo.
python run_backtest.py --symbol XAUUSD --style SCALPING INTRADAY SWING --balance 10000 %USE_AI_FLAG%
goto CHECK_ERROR

:CHECK_ERROR
if errorlevel 1 (
    echo.
    echo [ERROR] Backtest gagal. Semak output di atas.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   Backtest selesai! Report dibuka dalam browser.
echo ============================================================
pause
