@echo off
SET "VENV_PATH=G:\opt\software\python\modules"

:: --- STAGE 1: INFRASTRUCTURE ---
:: Only create the folder if it's missing
IF NOT EXIST "%VENV_PATH%\Scripts\activate.bat" (
    echo [SYS] Creating new virtual environment at %VENV_PATH%...
    python -m venv "%VENV_PATH%"
)

:: --- STAGE 2: ACTIVATION ---
:: This must happen before we can run pip or the script
call "%VENV_PATH%\Scripts\activate.bat"

:: --- STAGE 3: REQUIREMENTS ---
:: This runs every time. Pip is smart enough to see "Requirement already satisfied" 
:: and skip the download in milliseconds, but it ensures you're always up to date.
echo [SYNC] Ensuring dependencies are present...
python -m pip install --upgrade pip --quiet
pip install "numpy<2.4.0" pandas --quiet

:: --- STAGE 4: EXECUTION ---
cls
echo ==========================================
echo Environment: %VENV_PATH%
echo Status:      Ready (Intel-Legacy Optimized)
echo ==========================================