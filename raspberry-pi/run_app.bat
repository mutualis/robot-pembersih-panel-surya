@echo off
echo ========================================
echo Solar Panel Cleaner - Development Mode
echo ========================================
echo.

REM Set working directory to script location
pushd "%~dp0"

REM Check if venv311 exists
if exist "%~dp0..\venv311\Scripts\python.exe" (
    echo Using Python [venv311]
    "%~dp0..\venv311\Scripts\python.exe" run_dev.py %*
) else (
    echo venv311 tidak ditemukan!
    echo Pastikan venv311 ada di: %~dp0..\venv311\
    pause
    exit /b 1
)

if errorlevel 1 (
    echo.
    echo ========================================
    echo ERROR: Application failed to start
    echo ========================================
    pause
)

popd
