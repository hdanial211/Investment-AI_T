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
    echo [ERROR] Python tidak ditemui! Pastikan Python 3.8+ dipasang.
    pause
    exit /b 1
)

REM ── Install dependencies (sekali sahaja) ────────────────────
echo Checking dependencies...
pip install --quiet pandas numpy yfinance 2>nul
echo Dependencies OK.
echo.

REM ── Load settings from localStorage via helper ───────────────
REM Settings disimpan dalam backtest_settings.json oleh settings HTML page
REM run_backtest.py akan baca automatically

echo ============================================================
echo   Mode 1: Quick Run (default XAUUSD + All Styles)
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
    echo [INFO] XAUUSD + EURUSD, All Styles, Balance $10,000
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
