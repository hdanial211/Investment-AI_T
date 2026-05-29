@echo off
title GOLD AI - Visual Strategy Tester
echo =======================================================
echo     GOLD AI VISUAL STRATEGY TESTER LAUNCHER
echo =======================================================
echo.
echo Installing required web packages (Flask)...
python -m pip install flask flask-cors yfinance pandas requests python-dotenv --quiet

echo.
echo Starting Web Server...
echo Please wait... The browser will open automatically.

:: Start the Python server in the background
start /B python "visual_mode\server.py"

:: Wait 3 seconds for server to boot
timeout /t 3 /nobreak > NUL

:: Open default browser
start http://127.0.0.1:5000

echo.
echo [SERVER IS RUNNING]
echo Do not close this window while testing.
echo Press Ctrl+C to stop the server and exit.
pause > NUL
