@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Starting ArXiv Literature Assistant Web Server...
echo Server URL: http://localhost:8080
echo Press Ctrl+C to stop
python run_web.py
pause
