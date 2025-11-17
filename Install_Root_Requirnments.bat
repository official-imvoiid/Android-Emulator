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
