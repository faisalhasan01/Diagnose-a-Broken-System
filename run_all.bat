@echo off
title Django Project Launcher
echo ===================================================
echo   Launching Redis, Celery Worker, and Django Server
echo ===================================================
cd /d "%~dp0"

:: 1. Check and start Redis Server
netstat -ano | findstr :6379 >nul
if %errorlevel% equ 0 (
    echo [INFO] Redis is already running on port 6379.
) else (
    echo [INFO] Starting Redis Server...
    start "Redis Server" cmd /k ""C:\Users\faisal hasan\AppData\Local\Microsoft\WinGet\Packages\taizod1024.redis-windows-fork_Microsoft.Winget.Source_8wekyb3d8bbwe\Redis-8.8.0-Windows-x64-msys2\redis-server.exe""
    timeout /t 3 >nul
)

:: 2. Start Celery Task Worker
echo [INFO] Starting Celery worker...
start "Celery Worker" cmd /k "call .venv\Scripts\activate.bat && celery -A django_perf_assessment worker --loglevel=info -P threads"

:: 3. Start Django Server in this window
echo [INFO] Starting Django Web Server...
call .venv\Scripts\activate.bat
python manage.py runserver
