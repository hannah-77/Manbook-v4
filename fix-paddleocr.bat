@echo off
echo ========================================
echo Fixing PaddleOCR Installation
echo ========================================
echo.
echo This script will reinstall PaddleOCR with compatible versions
echo to fix the "ConvertPtrAttribute" error.
echo.
pause

cd /d "%~dp0backend"

echo.
echo [1/3] Uninstalling current versions...
pip uninstall paddlepaddle paddleocr -y

echo.
echo [2/3] Installing PaddlePaddle 2.6.0...
pip install paddlepaddle==2.6.0

echo.
echo [3/3] Installing PaddleOCR 2.7.0.3...
pip install paddleocr==2.7.0.3

echo.
echo ========================================
echo Installation Complete!
echo ========================================
echo.
echo Testing installation...
python -c "from paddleocr import PaddleOCR; print('PaddleOCR imported successfully')"

echo.
echo You can now run the backend with: start-backend.bat
pause
