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

:: Start Frontend - run pre-built exe if available, else build first
echo [2/2] Starting Frontend (Flutter)...
set FRONTEND_EXE=%~dp0frontend\build\windows\x64\runner\Release\frontend.exe
set FRONTEND_DBG=%~dp0frontend\build\windows\x64\runner\Debug\frontend.exe

if exist "%FRONTEND_EXE%" (
    start "Manbook Frontend" "%FRONTEND_EXE%"
    goto started
)
if exist "%FRONTEND_DBG%" (
    start "Manbook Frontend" "%FRONTEND_DBG%"
    goto started
)
start "Manbook Frontend" cmd /k "cd /d %~dp0frontend && flutter run -d windows"

:started
echo.
echo ==========================================
echo   Both services are starting!
echo   Backend:  http://127.0.0.1:8000
echo   Frontend: Flutter Windows App
echo ==========================================
echo.
echo Close this window anytime - services run independently.
pause
