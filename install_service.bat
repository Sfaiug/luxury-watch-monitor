@echo off
REM Watch Monitor Service Installation Script
REM Installs the Watch Monitor as a Windows Service
REM Requires Administrator privileges

setlocal EnableDelayedExpansion

echo.
echo ========================================
echo   Watch Monitor Service Installer
echo ========================================
echo.

REM Check if running as administrator
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo ❌ ERROR: Administrator privileges required!
    echo.
    echo Please run this batch file as Administrator:
    echo 1. Right-click on install_service.bat
    echo 2. Select "Run as administrator"
    echo.
    pause
    exit /b 1
)

echo ✅ Running with Administrator privileges
echo.

REM Check if Python is available
python --version >nul 2>&1
if %errorLevel% neq 0 (
    echo ❌ ERROR: Python not found in PATH!
    echo.
    echo Please ensure Python 3.8+ is installed and available in your PATH.
    echo You can download Python from: https://python.org/downloads/
    echo.
    pause
    exit /b 1
)

echo ✅ Python is available
python --version

REM Check Python version (basic check)
python -c "import sys; exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>&1
if %errorLevel% neq 0 (
    echo ❌ ERROR: Python 3.8 or higher is required!
    echo.
    python --version
    echo.
    pause
    exit /b 1
)

echo ✅ Python version is compatible
echo.

REM Check if we're in the correct directory
if not exist "windows_service.py" (
    echo ❌ ERROR: windows_service.py not found!
    echo.
    echo Please ensure you're running this batch file from the 
    echo watch monitor application directory.
    echo.
    pause
    exit /b 1
)

if not exist "main_production.py" (
    echo ❌ ERROR: main_production.py not found!
    echo.
    echo Please ensure you're running this batch file from the 
    echo watch monitor application directory.
    echo.
    pause
    exit /b 1
)

echo ✅ Application files found
echo.

REM Activate virtual environment if it exists
if exist "venv\Scripts\activate.bat" (
    echo 🔧 Activating Python virtual environment...
    call venv\Scripts\activate.bat
    echo ✅ Virtual environment activated
    echo.
) else if exist ".venv\Scripts\activate.bat" (
    echo 🔧 Activating Python virtual environment...
    call .venv\Scripts\activate.bat
    echo ✅ Virtual environment activated
    echo.
) else (
    echo ⚠️  No virtual environment found - using system Python
    echo.
)

REM Install Windows service dependencies if needed
echo 🔧 Checking Windows service dependencies...
python -c "import win32serviceutil" >nul 2>&1
if %errorLevel% neq 0 (
    echo 📦 Installing pywin32 package...
    pip install pywin32
    if %errorLevel% neq 0 (
        echo ❌ ERROR: Failed to install pywin32!
        echo.
        echo Please install manually with: pip install pywin32
        echo Then run: python -m win32api.install
        echo.
        pause
        exit /b 1
    )
    
    REM Configure pywin32
    echo 🔧 Configuring pywin32...
    python -m pywin32_postinstall -install
    if %errorLevel% neq 0 (
        echo ⚠️  pywin32 post-install had issues, but continuing...
    )
)

echo ✅ Windows service dependencies are ready
echo.

REM Check if service already exists
sc query "WatchMonitorService" >nul 2>&1
if %errorLevel% equ 0 (
    echo ⚠️  Service already exists! 
    echo.
    set /p "choice=Do you want to reinstall? This will stop and remove the existing service. (y/N): "
    if /i "!choice!" neq "y" (
        echo Installation cancelled.
        pause
        exit /b 0
    )
    
    echo 🛑 Stopping existing service...
    python windows_service.py stop
    timeout /t 3 /nobreak >nul
    
    echo 🗑️  Removing existing service...
    python windows_service.py remove
    timeout /t 2 /nobreak >nul
)

REM Validate environment configuration
echo 🔍 Validating environment configuration...
python main_production.py --validate >nul 2>&1
if %errorLevel% neq 0 (
    echo.
    echo ⚠️  Environment validation failed or has warnings.
    echo Running detailed validation...
    echo.
    python main_production.py --validate
    echo.
    set /p "choice=Continue with installation anyway? (y/N): "
    if /i "!choice!" neq "y" (
        echo Installation cancelled.
        echo.
        echo 💡 Tips:
        echo    1. Create a .env file with your Discord webhook URLs
        echo    2. Run: python main_production.py --create-env
        echo    3. Edit the generated .env.example file
        echo.  
        pause
        exit /b 0
    )
)

echo ✅ Environment validation passed (or bypassed)
echo.

REM Install the service
echo 🔧 Installing Windows Service...
python windows_service.py install

if %errorLevel% neq 0 (
    echo ❌ ERROR: Service installation failed!
    echo.
    echo This might be due to:
    echo 1. Insufficient privileges (run as Administrator)
    echo 2. Path issues with Python interpreter
    echo 3. Missing dependencies
    echo.
    pause
    exit /b 1
)

echo ✅ Service installed successfully!
echo.

REM Configure service for automatic restart on failure
echo 🔧 Configuring service for automatic restart on failure...
sc failure "WatchMonitorService" reset= 86400 actions= restart/30000/restart/60000/restart/120000 >nul
if %errorLevel% equ 0 (
    echo ✅ Service configured for automatic restart on failure
) else (
    echo ⚠️  Could not configure automatic restart (non-critical)
)

echo.
echo ========================================
echo   Installation Complete!
echo ========================================
echo.
echo Service Name: WatchMonitorService
echo Display Name: Watch Monitor Service
echo Status: Installed (Stopped)
echo.
echo Next Steps:
echo.
echo 1. Start the service:
echo    • Use: service_manager.bat
echo    • Or run: python windows_service.py start
echo    • Or use Windows Services Manager (services.msc)
echo.
echo 2. The service is configured to:
echo    • Auto-start when Windows boots
echo    • Restart automatically on failure
echo    • Log to Windows Event Log and file logs/
echo.
echo 3. Monitor the service:
echo    • Check Windows Event Viewer for service logs
echo    • Check logs/ directory for detailed application logs
echo    • Use: python windows_service.py debug (for troubleshooting)
echo.

set /p "choice=Would you like to start the service now? (Y/n): "
if /i "!choice!" neq "n" (
    echo.
    echo 🚀 Starting Watch Monitor Service...
    python windows_service.py start
    
    if %errorLevel% equ 0 (
        echo ✅ Service started successfully!
        echo.
        echo The Watch Monitor is now running as a Windows Service.
        echo It will automatically start when Windows boots.
    ) else (
        echo ❌ Failed to start service.
        echo.
        echo You can start it later with:
        echo   python windows_service.py start
        echo.
        echo Or check the logs for troubleshooting:
        echo   python windows_service.py debug
    )
)

echo.
echo 💡 Pro Tips:
echo    • Use service_manager.bat for easy service control
echo    • Check Event Viewer ^> Windows Logs ^> Application for service events
echo    • Service logs are in the logs/ directory
echo    • Use 'python windows_service.py debug' for troubleshooting
echo.

pause