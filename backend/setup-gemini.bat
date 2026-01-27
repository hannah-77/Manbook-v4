@echo off
echo ========================================
echo  Gemini Integration Setup
echo ========================================
echo.

cd /d "%~dp0"

echo [1/3] Installing Python dependencies...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)
echo.

echo [2/3] Checking .env configuration...
if not exist ".env" (
    echo ERROR: .env file not found!
    echo Please create .env file with your GEMINI_API_KEY
    pause
    exit /b 1
)

findstr /C:"your-api-key-here" .env >nul
if %errorlevel% equ 0 (
    echo.
    echo ========================================
    echo  WARNING: API Key Not Configured!
    echo ========================================
    echo.
    echo Please update .env file with your Gemini API key:
    echo 1. Get API key from: https://aistudio.google.com/app/apikey
    echo 2. Open .env file
    echo 3. Replace "your-api-key-here" with your actual API key
    echo.
    echo Example:
    echo GEMINI_API_KEY=AIzaSyABC123...
    echo.
    pause
    exit /b 1
)

echo [3/3] Testing Gemini connection...
python -c "from dotenv import load_dotenv; import os; load_dotenv(); key = os.getenv('GEMINI_API_KEY'); print('✓ API Key found:', key[:10] + '...' if key else 'NOT FOUND')"
if %errorlevel% neq 0 (
    echo ERROR: Failed to load API key
    pause
    exit /b 1
)
echo.

echo ========================================
echo  Setup Complete!
echo ========================================
echo.
echo Vision Mode: HYBRID (Gemini + PaddleOCR)
echo.
echo To start the backend:
echo   python main.py
echo.
echo Or use the start-backend.bat script
echo.
pause
