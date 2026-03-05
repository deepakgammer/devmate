@echo off
REM ─────────────────────────────────────────────────────────────────────────
REM  DEVMATE – Windows One-Click Installer
REM  Run this from the DevMate directory to set up the Python environment.
REM ─────────────────────────────────────────────────────────────────────────

TITLE DEVMATE Installer

echo.
echo  ████████████████████████████████████████████
echo  ██    DEVMATE – Installing Dependencies    ██
echo  ████████████████████████████████████████████
echo.

REM Check Python availability
python --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo [ERROR] Python not found. Please install Python 3.10+ from https://python.org
    pause
    exit /b 1
)

echo [1/5] Creating virtual environment ...
python -m venv .venv
IF ERRORLEVEL 1 (
    echo [ERROR] Failed to create virtual environment.
    pause
    exit /b 1
)

echo [2/5] Activating virtual environment ...
call .venv\Scripts\activate.bat

echo [3/5] Upgrading pip ...
python -m pip install --upgrade pip --quiet

echo [4/5] Installing Python dependencies ...
pip install -r requirements.txt
IF ERRORLEVEL 1 (
    echo [ERROR] pip install failed. Check requirements.txt and your internet connection.
    pause
    exit /b 1
)

echo [5/5] Creating data directory ...
if not exist "data" mkdir data

echo.
echo  ============================================
echo   Installation complete!
echo  ============================================
echo.
echo  BEFORE running DEVMATE:
echo   1. Install Ollama: https://ollama.ai
echo   2. Pull the model:  ollama pull llama3:8b-instruct-q4_0
echo   3. Start Ollama:    ollama serve  (keep terminal open)
echo.
echo  To start DEVMATE:
echo    .venv\Scripts\activate.bat
echo    python devmate.py
echo.
pause
