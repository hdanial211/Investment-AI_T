@echo off
title Investment-AI_T - Start
cd /d "%~dp0"

if not exist "%~dp0Bot Engine\start_bot.bat" (
    echo.
    echo  [ERROR] Internal launcher not found:
    echo          %~dp0Bot Engine\start_bot.bat
    echo.
    echo  Please make sure the Bot Engine folder is still beside this file.
    echo.
    pause
    exit /b 1
)

call "%~dp0Bot Engine\start_bot.bat"
exit /b %ERRORLEVEL%
