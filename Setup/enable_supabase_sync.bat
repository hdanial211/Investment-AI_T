@echo off
setlocal

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0enable_supabase_sync.ps1" %*
exit /b %ERRORLEVEL%
