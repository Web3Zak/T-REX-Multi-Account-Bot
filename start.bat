@echo off
title T-Rex Bot Launcher
color 0A

echo ============================================
echo      Starting T-Rex BOT (Playwright)
echo ============================================
echo.

REM --- проверяем Python ---
echo Checking Python...
python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python не найден. Установите Python 3.10+ и добавьте его в PATH.
    pause
    exit /b
)

REM --- проверяем requirements.txt ---
IF NOT EXIST requirements.txt (
    echo requirements.txt не найден!
    echo Создайте файл requirements.txt со списком зависимостей.
    pause
    exit /b
)

REM --- установка зависимостей ---
echo Installing dependencies...
pip install -r requirements.txt

REM --- установка Playwright Chromium ---
echo Installing Playwright Chromium (если необходимо)...
python -m playwright install chromium

echo.
echo ============================================
echo                 Launching
echo ============================================
echo.

REM --- запуск основного скрипта ---
python trex_daily_script.py

echo.
echo ============================================
echo   Скрипт завершён. Нажмите любую клавишу.
echo ============================================
pause