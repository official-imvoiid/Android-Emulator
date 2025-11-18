@echo off

:: Script to check Python installation, upgrade pip, and install dependencies from requirements.txt
echo Checking Python installation...
python --version >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Python is installed
    python --version
) else (
    echo [ERROR] Python not found. Please download and install Python 3.12 or a stable LTS version from https://www.python.org/downloads/
    echo [INFO] Alternatively, use Install_Root_Requirements.bat to install Python and other root dependencies
    exit /b 1
)

:: Check if pip is installed
echo Checking pip installation...
pip --version >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] pip is installed
    pip --version
    echo [INFO] Upgrading pip to the latest version...
    python -m pip install --upgrade pip
    if %errorlevel% equ 0 (
        echo [OK] pip upgraded successfully
    ) else (
        echo [WARNING] Failed to upgrade pip. Continuing with existing version...
    )
) else (
    echo [ERROR] pip not found. Please ensure pip is installed with Python.
    exit /b 1
)

:: Check if requirements.txt exists and is not empty
if exist requirements.txt (
    for %%F in (requirements.txt) do (
        if %%~zF equ 0 (
            echo [ERROR] requirements.txt is empty.
            exit /b 1
        )
    )
    echo [INFO] Installing Python dependencies from requirements.txt...
    pip install -r requirements.txt
    if %errorlevel% equ 0 (
        echo [DONE] Python dependencies installed successfully
    ) else (
        echo [ERROR] Failed to install dependencies. Please check requirements.txt or your network connection.
        exit /b 1
    )
) else (
    echo [ERROR] requirements.txt not found in the current directory.
    exit /b 1
)

echo [INFO] Script completed.
pause
exit /b 0
