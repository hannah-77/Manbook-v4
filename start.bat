@echo off
echo ==========================================
echo   Manbook-v4 - Starting Application
echo ==========================================
echo.

:: Start Backend (new window)
echo [1/2] Starting Backend (Python)...
start "Manbook Backend" cmd /k "cd /d %~dp0backend && call venv311\Scripts\activate && python main.py"

:: Wait for backend to initialize
timeout /t 3 /nobreak > nul

:: Start Frontend (new window)
echo [2/2] Starting Frontend (Flutter)...
start "Manbook Frontend" cmd /k "cd /d %~dp0frontend && flutter run -d windows"

echo.
echo ==========================================
echo   Both services are starting!
echo   Backend:  http://127.0.0.1:8000
echo   Frontend: Flutter Windows App
echo ==========================================
echo.
echo Close this window anytime - services run independently.
pause
