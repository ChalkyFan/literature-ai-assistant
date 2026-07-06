@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo   ArXiv Literature Assistant Web Server
echo ========================================
echo.
echo Server will auto-restart if it crashes.
echo Close this window to stop the server.
echo.

:restart
echo [%date% %time%] Starting server...
python run_web.py
echo [%date% %time%] Server stopped, restarting in 3 seconds...
timeout /t 3 /nobreak >nul
goto restart
