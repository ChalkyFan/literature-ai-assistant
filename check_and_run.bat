@echo off
cd /d D:\literature_AI_assistant
D:\ProgramData\anaconda3\python.exe check_today.py
if errorlevel 2 (
    echo Running pipeline...
    D:\ProgramData\anaconda3\python.exe run_pipeline.py
) else (
    echo Papers already fetched. Skipping.
)
echo Running data backup...
D:\ProgramData\anaconda3\python.exe backup_data.py
exit /b 0