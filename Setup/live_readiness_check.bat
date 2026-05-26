@echo off
setlocal
title Investment-AI_T - Phase 9 Live Readiness
cd /d "%~dp0.."

echo.
echo  ============================================================
echo    PHASE 9 LIVE READINESS CHECK
echo  ============================================================
echo.

python "Setup\live_readiness_check.py" %*
set "RESULT=%ERRORLEVEL%"

echo.
if not "%RESULT%"=="0" (
    echo  Readiness check found blocking issue(s).
) else (
    echo  Readiness check passed.
)
echo.
pause
exit /b %RESULT%
