@echo off
echo ========================================
echo Starting Manbook Backend Server
echo ========================================
echo.

cd /d "%~dp0backend"

REM Use venv311 Python directly (no activate needed)
if exist "venv311\Scripts\python.exe" (
    echo Using venv311 Python 3.11 (Surya + CUDA)...
    set PYTHON_CMD=venv311\Scripts\python.exe
) else if exist "venv\Scripts\python.exe" (
    echo WARNING: venv311 not found, falling back to venv...
    set PYTHON_CMD=venv\Scripts\python.exe
) else (
    echo No virtual environment found, using system Python...
    set PYTHON_CMD=python
)

REM Check if requirements are installed
%PYTHON_CMD% -c "import fastapi" 2>nul
if errorlevel 1 (
    echo Installing dependencies...
    %PYTHON_CMD% -m pip install -r requirements.txt
)

echo.
echo Starting FastAPI server on http://127.0.0.1:8000
echo Press Ctrl+C to stop
echo.

%PYTHON_CMD% main.py

pause
