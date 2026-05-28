@echo off
title Auto-Installer untuk VPS (Python & Git)
color 0B
cls

echo ============================================================
echo   AUTO-INSTALLER UNTUK VPS WINDOWS
echo   (Python 3.10 ^& Git for Windows)
echo ============================================================
echo.
echo Pastikan VPS anda mempunyai sambungan Internet sebelum bermula.
echo Proses ini akan download dan install secara automatik (senyap).
echo.
pause

cd /d "%~dp0"

echo.
echo [1/4] Sedang download Python 3.10.11...
powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.10.11/python-3.10.11-amd64.exe' -OutFile 'python-installer.exe'"
if not exist "python-installer.exe" (
    echo [ERROR] Gagal download Python. Sila check Internet VPS.
    pause
    exit /b 1
)

echo [2/4] Sedang install Python 3.10 (Sila tunggu...)...
start /wait python-installer.exe /quiet InstallAllUsers=1 PrependPath=1 Include_test=0
echo       Python selesai di-install!
del python-installer.exe

echo.
echo [3/4] Sedang download Git for Windows...
powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://github.com/git-for-windows/git/releases/download/v2.45.1.windows.1/Git-2.45.1-64-bit.exe' -OutFile 'git-installer.exe'"
if not exist "git-installer.exe" (
    echo [ERROR] Gagal download Git. Sila install secara manual.
    pause
    exit /b 1
)

echo [4/4] Sedang install Git (Sila tunggu...)...
start /wait git-installer.exe /VERYSILENT /NORESTART
echo       Git selesai di-install!
del git-installer.exe

echo.
echo ============================================================
echo   PEMASANGAN SELESAI BERJAYA! ✅
echo ============================================================
echo.
echo Sila TUTUP tetingkap ini, dan BUKA SEMULA Terminal/CMD baru 
echo supaya Windows kenal command "python" dan "git".
echo Lepas tu, awak boleh jalankan start_bot.bat seperti biasa.
echo.
pause
