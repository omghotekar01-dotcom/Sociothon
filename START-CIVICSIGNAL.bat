@echo off
setlocal
title CivicSignal 360 - Local Server
cd /d "%~dp0"
echo.
echo ================================================
echo              CivicSignal 360
echo ================================================
echo.
if not exist ".venv\Scripts\python.exe" (
    echo Python setup is missing in this project folder.
    echo Follow the first-time setup instructions in README.md.
    echo.
    pause
    exit /b 1
)
echo Starting the project. Your browser will open when ready.
echo First startup may take a little longer to prepare demo data.
echo Keep this window open while using the project.
echo Press Ctrl+C here to stop the server and worker.
echo.
".venv\Scripts\python.exe" "scripts\run.py" --open-browser
set "CIVIC_EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%CIVIC_EXIT_CODE%"=="0" (
    echo Startup stopped with an error. Read the message above.
    echo If the frontend build is missing, run: pnpm --dir apps/web build
    echo.
    pause
)
exit /b %CIVIC_EXIT_CODE%
