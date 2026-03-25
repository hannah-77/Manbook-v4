@echo off
echo ========================================
echo Installing GPU Dependencies for Manbook
echo ========================================
echo.
cd /d "%~dp0backend"

REM Check if environment is activated
if not exist "venv\Scripts\activate.bat" (
    echo Error: Virtual environment not found in backend/venv.
    pause
    exit /b
)

echo Activating Virtual Environment...
call venv\Scripts\activate.bat

echo.
echo [1/2] Uninstalling CPU versions...
pip uninstall -y paddlepaddle torch torchvision torchaudio

echo.
echo [2/2] Installing GPU versions...
echo ~ Installing PaddlePaddle GPU...
pip install paddlepaddle-gpu==2.6.2

echo.
echo ~ Installing PyTorch GPU (CUDA 12.4)...
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124

echo.
echo ========================================
echo GPU Dependencies Installed Successfully!
echo ========================================
pause
