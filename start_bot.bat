@echo off
title Investment-AI_T - Start
cd /d "%~dp0"

echo ============================================================
echo   1. MENDAPATKAN UPDATE TERBARU (GIT PULL)
echo ============================================================
git pull
echo.

echo ============================================================
echo  :: ── STEP 2: Start Desktop Command Center (background) ───────────
echo  [2/4] Memulakan Desktop Command Center...
if exist "%~dp0desktop_launcher.py" (
    pythonw --version >nul 2>&1
    if not errorlevel 1 (
        start "Desktop Command Center" /B pythonw desktop_launcher.py
        echo        Desktop Command Center started (using pythonw).
    ) else (
        py -w --version >nul 2>&1
        if not errorlevel 1 (
            start "Desktop Command Center" /B py -w desktop_launcher.py
            echo        Desktop Command Center started (using py -w).
        ) else (
            echo        [ERROR] Python is not installed or not in PATH!
            echo        Sila run VPS_Setup\Install_VPS_Requirements.bat dahulu.
            pause
            exit /b 1
        )
    )
) else (
    echo        [SKIP] desktop_launcher.py tidak dijumpai.
)
exit /b 0