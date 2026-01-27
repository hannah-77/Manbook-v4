@echo off
echo ========================================
echo   MANBOOK-V4 WINDOWS APP BUILDER
echo ========================================
echo.

REM Step 1: Build Flutter Windows App
echo [1/4] Building Flutter Windows App...
cd frontend
call flutter build windows --release
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Flutter build failed!
    pause
    exit /b 1
)
echo ✓ Flutter build complete!
echo.

REM Step 2: Build Backend Executable
echo [2/4] Building Backend Executable...
cd ..\backend
call pip install pyinstaller
call pyinstaller --onefile --name manbook-backend main.py
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Backend build failed!
    pause
    exit /b 1
)
echo ✓ Backend build complete!
echo.

REM Step 3: Package Application
echo [3/4] Packaging Application...
cd ..
if not exist "dist" mkdir dist
if not exist "dist\Manbook-v4" mkdir "dist\Manbook-v4"

REM Copy Flutter app
xcopy /E /I /Y "frontend\build\windows\x64\runner\Release" "dist\Manbook-v4\app"

REM Copy Backend
if not exist "dist\Manbook-v4\app\data" mkdir "dist\Manbook-v4\app\data"
if not exist "dist\Manbook-v4\app\data\bin" mkdir "dist\Manbook-v4\app\data\bin"
copy "backend\dist\manbook-backend.exe" "dist\Manbook-v4\app\data\bin\backend.exe"

REM Copy reference files
copy "backend\reference.csv" "dist\Manbook-v4\app\data\bin\"

echo ✓ Packaging complete!
echo.

REM Step 4: Create Shortcuts
echo [4/4] Creating Shortcuts...
cd dist\Manbook-v4

REM Create README
echo MANBOOK-V4 - Manual Book Auto-Standardizer > README.txt
echo. >> README.txt
echo HOW TO RUN: >> README.txt
echo 1. Double-click "Manbook-v4.exe" in the app folder >> README.txt
echo 2. Wait for AI Engine to initialize >> README.txt
echo 3. Upload your manual book (PDF/Image) >> README.txt
echo 4. Download the standardized Word/PDF report >> README.txt
echo. >> README.txt
echo REQUIREMENTS: >> README.txt
echo - Windows 10/11 (64-bit) >> README.txt
echo - No additional software needed! >> README.txt

cd ..\..

echo ✓ Build complete!
echo.
echo ========================================
echo   BUILD SUCCESSFUL!
echo ========================================
echo.
echo Your application is ready at:
echo   dist\Manbook-v4\
echo.
echo To distribute:
echo   1. Zip the "Manbook-v4" folder
echo   2. Send to users
echo   3. Users extract and run "app\frontend.exe"
echo.
pause
