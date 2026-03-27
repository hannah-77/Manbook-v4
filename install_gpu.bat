@echo off
echo ====================================================
echo   Menginstalasi Driver AI GPU (RTX 4050 CUDA)...
echo ====================================================
echo.

:: Masuk ke folder backend
cd /d %~dp0backend

:: Mengaktifkan virtual environment
call venv311\Scripts\activate.bat

echo [1/4] Menghapus versi CPU murni yang lama...
pip uninstall -y torch torchvision torchaudio paddlepaddle
echo.

echo [2/4] Mengunduh PyTorch dengan dukungan CUDA 12.1...
echo (Ini adalah file besar ~2.5GB, mohon bersabar)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
echo.

echo [3/4] Mengunduh PaddlePaddle versi GPU...
pip install paddlepaddle-gpu
echo.

echo [4/4] Memastikan semuanya beres...
python -c "import torch; print('Torch GPU:', torch.cuda.is_available())"
python -c "import paddle; print('Paddle GPU:', paddle.device.is_compiled_with_cuda())"

echo.
echo ====================================================
echo   Instalasi Selesai! 
echo   Silakan jalankan ulang start.bat Anda.
echo ====================================================
pause
