@echo off
echo ========================================
echo Starting Manbook Full Stack App
echo ========================================
echo.
echo This will start both:
echo 1. Backend Server (Python FastAPI)
echo 2. Flutter Frontend
echo.
echo Press any key to continue...
pause >nul

cd /d "%~dp0"

REM Start backend in a new window
echo Starting Backend Server...
start "Manbook Backend" cmd /k call start-backend.bat

REM Wait a bit for backend to initialize
timeout /t 3 /nobreak >nul

REM Start Flutter in a new window
echo Starting Flutter App...
start "Manbook Flutter" cmd /k call start-flutter.bat

echo.
echo ========================================
echo Both services are starting!
echo ========================================
echo Backend: http://127.0.0.1:8000
echo Check the new windows for status
echo.
echo Press any key to exit this window...
pause >nul
