@echo off

:: Check for Admin Rights
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Requires administrative privileges...
    powershell -command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

echo ====================================
echo Development Environment Setup
echo ====================================
echo.

:: ====================================
:: STEP 1: Check and Install Docker
:: ====================================
echo [Step 1] Checking the Docker installation...
docker --version >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Docker is already installed
    docker --version
) else (
    echo [INFO] Docker not found. Installing via winget...
    echo.
    
    :: Check if winget exists
    where winget >nul 2>&1
    if %errorlevel% neq 0 (
        echo [ERROR] winget not found!
        echo Please install App Installer from Microsoft Store.
        pause
        exit /b 1
    )
    
    :: Update winget sources
    echo Updating winget sources...
    winget source update 
    
    :: Install Docker Desktop with auto-accept
    echo Installing Docker Desktop...
    winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements 
    
    if %errorLevel% equ 0 (
        echo [OK] Docker installed successfully!
    ) else (
        echo [WARNING] Docker installation may have failed. Check manually.
    )
)
echo.

:: ====================================
:: STEP 2: Check and Install Python
:: ====================================
echo [STEP 2] Checking Python installation...
python --version >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Python is already installed
    python --version 
) else (
    echo [INFO] Python not found. Installing Python 3.12...
    echo.

    :: Install Python 3.12 with auto-accept
    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    
    if %errorLevel% equ 0 (
        echo [OK] Python 3.12 installed successfully!
        :: Refresh PATH for current session
        call refreshenv >nul 2>&1
    ) else (
        echo [WARNING] Python installation may have failed. Check manually.
    )
)
echo.

:: ====================================
:: STEP 3: Install Android SDK Manager
:: ====================================
echo [STEP 3] Installing Android SDK Command-line Tools...
echo.

:: Set installation directory 
set "INSTALL_DIR=C:\Program Files\Google\sdkmanager"
set "SDK_HOME=%INSTALL_DIR%\cmdline-tools\latest"
set "ANDROID_HOME=%INSTALL_DIR%"

:: Download URL for latest command-line tools (Windows)
set "DOWNLOAD_URL=https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip"
set "TEMP_ZIP=%TEMP%\cmdline-tools.zip"

echo Installation Directory: %INSTALL_DIR%
echo.

:: Create installation directory
if not exist "%INSTALL_DIR%" (
    echo Creating installation directory...
    mkdir "%INSTALL_DIR%"
)

:: Download command-line tools
echo Downloading Android SDK Command-line Tools...
echo This may take a few minutes...
echo.

powershell -Command "& {[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; $ProgressPreference = 'SilentlyContinue'; Invoke-WebRequest -Uri '%DOWNLOAD_URL%' -OutFile '%TEMP_ZIP%'; Write-Host 'Download complete!'}"

if %errorLevel% neq 0 (
    echo [ERROR] Download failed!
    pause
    exit /b 1
)

:: Extract zip files
echo Extracting files...
powershell -Command "Expand-Archive -Path '%TEMP_ZIP%' -DestinationPath '%INSTALL_DIR%' -Force"

if %errorLevel% neq 0 (
    echo [ERROR] Extraction failed!
    pause
    exit /b 1
)

:: Reorganize directory structure
echo Organizing directory structure...
if exist "%INSTALL_DIR%\cmdline-tools" (
    if not exist "%INSTALL_DIR%\cmdline-tools\latest" (
        powershell -Command "Move-Item -Path '%INSTALL_DIR%\cmdline-tools' -Destination '%TEMP%\cmdline-tools-temp' -Force; New-Item -ItemType Directory -Path '%INSTALL_DIR%\cmdline-tools\latest' -Force; Move-Item -Path '%TEMP%\cmdline-tools-temp\*' -Destination '%INSTALL_DIR%\cmdline-tools\latest\' -Force; Remove-Item '%TEMP%\cmdline-tools-temp' -Force"
    )
)

:: Clean up temporary files
del "%TEMP_ZIP%" /f /q

echo [OK] Android SDK extracted successfully!
echo.

:: ====================================
:: STEP 4: Set Environment Variables
:: ====================================
echo [STEP 4] Setting environment variables...
echo.

:: Set ANDROID_HOME environment variable
setx ANDROID_HOME "%ANDROID_HOME%" /M >nul 2>&1
if %errorLevel% equ 0 (
    echo [OK] ANDROID_HOME set to: %ANDROID_HOME%
) else (
    echo [WARNING] Failed to set ANDROID_HOME environment variable.
)

:: Add SDK tools to PATH
setx PATH "%PATH%;%ANDROID_HOME%\cmdline-tools\latest\bin;%ANDROID_HOME%\platform-tools" /M >nul 2>&1
if %errorLevel% equ 0 (
    echo [OK] Android SDK tools added to PATH
) else (
    echo [WARNING] Failed to update PATH environment variable.
)

echo.
echo ********************************************************************                                                                *
echo *                      Setup Complete!                             *                                                                 *
echo ********************************************************************
echo *   Please restart your computer for changes to take effect.       *
echo ********************************************************************
echo.

pause