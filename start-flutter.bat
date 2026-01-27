@echo off
echo ========================================
echo Starting Manbook Flutter App
echo ========================================
echo.

cd /d "%~dp0frontend"

REM Check if Flutter is installed
flutter --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Flutter is not installed or not in PATH
    echo Please install Flutter: https://flutter.dev/docs/get-started/install
    pause
    exit /b 1
)

REM Get dependencies if needed
if not exist "pubspec.lock" (
    echo Getting Flutter dependencies...
    flutter pub get
)

echo.
echo Starting Flutter app...
echo.

flutter run

pause
