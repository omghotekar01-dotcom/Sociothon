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
echo Building the latest welcome page and frontend...
where pnpm >nul 2>&1
if errorlevel 1 (
    echo pnpm is missing. Install it with: npm install -g pnpm@11.25.0
    pause
    exit /b 1
)
call pnpm --dir apps/web build
if errorlevel 1 (
    echo Frontend build failed. Review the error above before starting the server.
    pause
    exit /b 1
)
echo Opening the Quick Start welcome page at http://127.0.0.1:8000/start
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
