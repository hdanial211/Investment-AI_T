@echo off
title Investment-AI Microservices Launcher
echo ========================================================
echo   STARTING INVESTMENT-AI MICROSERVICES (2 TERMINALS)
echo ========================================================

cd /d "%~dp0"

echo Starting Terminal 1: AI Trader (main.py)...
start "AI Trader [Microservice]" cmd /k "cd Bot Engine && python main.py"
timeout /t 5 /nobreak >nul

echo Starting Terminal 3: Active Trade Manager (terminal_trade_manager.py)...
start "Active Trade Manager [Microservice]" cmd /k "cd Bot Engine && python terminal_trade_manager.py"

echo All terminals launched! You can close this launcher window.
pause
