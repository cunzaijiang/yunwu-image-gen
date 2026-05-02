@echo off
chcp 65001 >nul 2>&1
echo ===================================
echo   YunwuAI Image Generator - Build
echo ===================================

echo [1/3] Installing Python dependencies...
pip install requests Pillow tkinterdnd2 pyinstaller
if errorlevel 1 (
    echo ERROR: pip install failed. Make sure Python is in PATH.
    pause
    exit /b 1
)

echo [2/3] Building exe with PyInstaller...
pyinstaller --noconfirm --onefile --windowed --name "YunwuImageGen" main.py

echo [3/3] Done!
if exist "dist\YunwuImageGen.exe" (
    echo.
    echo Build successful! Output: dist\YunwuImageGen.exe
    echo.
    explorer dist
) else (
    echo Build may have failed. Check logs above.
)
pause
