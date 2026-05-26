@echo off
setlocal

cd /d "%~dp0.."
python "Setup\run_smoke_tests.py"
exit /b %ERRORLEVEL%
