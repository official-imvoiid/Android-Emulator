@echo  off

:: Check for Admin Rights
if net session >nul 2>&1
%errorLevel% neq 0 (
    echo Requires administrative privileges...
    powershell -command "Start-Process '%~f0' -Verb RunAs"
    exist /b
)

echo ====================================
echo Development Environment Setup
echo ====================================
echo.

:: ====================================
:: STEP 1: Check and Install Docker
:: ====================================
echo [Step 1] Checking the Docker installation....
docker --version >null 2>&1
if %errorlevel% equ 0 (
	echo [OK] Docker is already installed
	docker --version
) else (
	echo [INFO] Docker not found. Installing via winget...
	echo .
	
	:: Check if winget exist.
	where winget >nul 2>&1
	if %errorlevel% neq 0 (
		echo [Error] winget not found!
		echo Please install App Installer from Microsoft Store.
		pause
		exit /b 1
	)
	
	:: Update winge sources
	echo Updating winget sources...
	winget source update 
	
	:: Install Docker Desktop with auto-accept
	echo Installing Docker Desktop...
	winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements 
	
	if %errorLevel% equ 0 (
		echo [OK] Docker installed successfully!
	) else (
		
    
    if %errorLevel% equ 0 (
        
    ) else (
        echo [WARNING] Docker installation may have failed. Check manually.
    )
	
echo.

:: ====================================
:: STEP 2: Check and Install Python
:: ====================================
echo [STEP 2] Checking Python installation...
python --version >null 2>&1
	echo [OK] Python is already installed
	python --version 
) else (
	echo [INFO] Python not found. Installing Python 3.12...
	echo .

    :: Install Python 3.12 with auto-accept
    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    
	if %errorLevel% equ 0 (
		echo [OK] 
		Python 3.12 installed successfully!
		:: Refresh PATH for current session
		call refreshenv >nul 2>&1
	) else (
		echo [WARNING] Python installation may have failed. Check manually.
	)
)
echo .
