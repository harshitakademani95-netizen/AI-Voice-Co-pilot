@echo off
title Voicebot Backend Server (Port 8000)
cd /d "%~dp0"
echo ===================================================
echo Starting AI Voicebot SDE-3 Backend on Port 8000...
echo Keep this window OPEN while testing in browser.
echo ===================================================

echo Opening browser in 3 seconds...
start /b cmd /c "timeout /t 3 /nobreak >nul & start http://127.0.0.1:8000/ui"

python -m uvicorn src.app:app --host 127.0.0.1 --port 8000
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Uvicorn failed. Starting built-in server.py fallback on port 8000...
    python server.py 8000
)

echo.
echo Server has stopped.
pause
