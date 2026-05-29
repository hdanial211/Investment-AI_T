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
echo   Mode 1: Quick Run (default XAUUSD + EURUSD, All Styles)
echo   Mode 2: Custom Settings - buka backtest_settings.html dulu
echo ============================================================
echo.

REM ── Check if settings file exists ───────────────────────────
if exist "backtest_settings.json" (
    echo [INFO] Settings file found - menggunakan custom settings...
    echo.
    python run_backtest.py
) else (
    echo [INFO] Tiada settings file - menggunakan defaults...
    echo [INFO] Symbol: XAUUSD + EURUSD ^| Styles: All ^| Balance: $10,000
    echo [INFO] Data: 1 tahun lepas sehingga hari ini ^(auto-download^)
    echo.
    python run_backtest.py --symbol XAUUSD EURUSD --style SCALPING INTRADAY SWING --balance 10000
)

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
