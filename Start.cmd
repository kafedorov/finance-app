@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Local Python environment is missing. See README.md.
    pause
    exit /b 1
)
set "APP_ENV=development"
echo Svod: http://127.0.0.1:8765
echo Keep this window open. Press Ctrl+C to stop the server.
".venv\Scripts\python.exe" -m uvicorn backend.asgi:app --host 127.0.0.1 --port 8765 --no-access-log
if errorlevel 1 (
    echo.
    echo Startup failed. See the error above.
    pause
    exit /b 1
)
