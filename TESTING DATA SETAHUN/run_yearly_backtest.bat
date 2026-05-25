@echo off
setlocal

cd /d "%~dp0"

echo ============================================================
echo    INVESTMENT-AI_T - 1 YEAR BACKTEST REPORT
echo ============================================================
echo.
echo This will use MT5 history if available.
echo If MT5 is not available, the HTML report will stay Pending.
echo Duplicate protection is ON. If this file is opened twice,
echo the second run will stop instead of writing duplicate results.
echo After the first full-year baseline, normal runs will not repeat
echo the same year again. If the bot was offline too long, it resumes
echo from the last tested/live-data date automatically.
echo.

python run_yearly_backtest.py

echo.
echo ============================================================
echo    Backtest command finished. Press any key to close.
echo ============================================================
pause >nul
