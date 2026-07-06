@echo off
cd /d D:\文献AI助手
D:\ProgramData\anaconda3\python.exe check_today.py
if errorlevel 2 (
    echo Running pipeline...
    D:\ProgramData\anaconda3\python.exe run_pipeline.py
) else (
    echo Papers already fetched. Skipping.
)
exit /b 0
