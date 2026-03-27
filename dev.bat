@echo off
echo ==========================================
echo   Manbook-v4 - DEVELOPMENT MODE
echo ==========================================
echo.

:: Start Backend with Uvicorn Auto-Reload
echo [1/2] Starting Backend (Auto-Reload enabled)...
start "Manbook Backend DEV" cmd /k "cd /d %~dp0backend && call venv311\Scripts\activate && uvicorn main:app --host 127.0.0.1 --port 8000 --reload"

timeout /t 3 /nobreak > nul

:: Start Frontend with Flutter Hot-Reload
echo [2/2] Starting Frontend (Hot-Reload enabled)...
start "Manbook Frontend DEV" cmd /k "cd /d %~dp0frontend && flutter run -d windows"

echo.
echo ==========================================
echo   Development services are starting!
echo   * Backend will auto-reload when .py files are saved.
echo   * For Frontend, go to the new "Manbook Frontend DEV" terminal and press 'r' to Hot Reload UI cleanly!
echo ==========================================
pause
