@echo off
chcp 65001 >nul
title Build Mamp Poo.exe
echo ============================================
echo  Build Mamp Poo.exe
echo ============================================
echo.

echo [1/4] Install dependencies + PyInstaller...
pip install --quiet -r requirements.txt
pip install --quiet pyinstaller
if errorlevel 1 (
    echo ERROR: cannot install PyInstaller
    pause & exit /b 1
)

echo [2/4] Convert crab_logo.png to .ico...
python -c "from PIL import Image; Image.open('crab_logo.png').save('crab_logo.ico', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])"
if errorlevel 1 (
    echo WARN: cannot make .ico, building without icon
)

echo [3/4] Build .exe (may take 1-2 minutes)...
pyinstaller ^
    --onefile ^
    --noconsole ^
    --name "Mamp Poo" ^
    --icon "crab_logo.ico" ^
    --add-data "manager;manager" ^
    --add-data "ui;ui" ^
    --add-data "crab_logo.png;." ^
    --hidden-import customtkinter ^
    --hidden-import PIL ^
    --hidden-import requests ^
    --hidden-import pystray ^
    --hidden-import pystray._win32 ^
    main.py

if errorlevel 1 (
    echo ERROR: build failed
    pause & exit /b 1
)

echo [4/4] Done!
echo.
echo Output: dist\Mamp Poo.exe
echo Distribute this single .exe file to other computers
echo.
pause
