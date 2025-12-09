@echo off
title T-Rex Bot Launcher
color 0A
cls

:: ======================================================
::                    ASCII BANNER
:: ======================================================
echo.
echo   ________________________________________________
echo   |                                              |
echo   |   T R E X   A U T O M A T I O N   B O T      |
echo   |______________________________________________|
echo.
echo   Fast, stable and fully automated browser engine
echo   ------------------------------------------------
echo.

echo [1] Checking Python...
python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Python не найден!
    echo Установите Python 3.10+ и добавьте его в PATH.
    echo.
    pause
    exit /b
)
echo     → Python detected.

echo.
echo [2] Checking requirements.txt...
IF NOT EXIST requirements.txt (
    echo.
    echo [ERROR] requirements.txt не найден!
    echo Создайте его со списком зависимостей.
    echo.
    pause
    exit /b
)
echo     → File found.

echo.
echo [3] Installing pip dependencies...
pip install -r requirements.txt

echo.
echo ======================================================
echo      L A U N C H I N G   T - R E X   B O T
echo ======================================================
echo.

python trex_daily_script.py

echo.
echo ======================================================
echo                 SCRIPT FINISHED
echo        Press any key to close this window...
echo ======================================================
pause >nul