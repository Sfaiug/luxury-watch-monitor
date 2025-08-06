@echo off
REM Watch Monitor Service Uninstallation Script
REM Removes the Watch Monitor Windows Service
REM Requires Administrator privileges

setlocal EnableDelayedExpansion

echo.
echo ========================================
echo   Watch Monitor Service Uninstaller
echo ========================================
echo.

REM Check if running as administrator
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo ❌ ERROR: Administrator privileges required!
    echo.
    echo Please run this batch file as Administrator:
    echo 1. Right-click on uninstall_service.bat
    echo 2. Select "Run as administrator"
    echo.
    pause
    exit /b 1
)

echo ✅ Running with Administrator privileges
echo.

REM Check if service exists
sc query "WatchMonitorService" >nul 2>&1
if %errorLevel% neq 0 (
    echo ⚠️  Watch Monitor Service is not installed.
    echo.
    echo Nothing to uninstall.
    echo.
    pause
    exit /b 0
)

echo 🔍 Found Watch Monitor Service
echo.

REM Get service status
for /f "tokens=3" %%i in ('sc query "WatchMonitorService" ^| find "STATE"') do set "service_state=%%i"

echo Current service state: !service_state!
echo.

REM Confirm uninstallation
echo ⚠️  WARNING: This will permanently remove the Watch Monitor Service.
echo.
set /p "choice=Are you sure you want to uninstall the service? (y/N): "
if /i "!choice!" neq "y" (
    echo Uninstallation cancelled.
    pause
    exit /b 0
)

echo.
echo 🛑 Proceeding with service uninstallation...
echo.

REM Stop the service if it's running
if /i "!service_state!" equ "RUNNING" (
    echo 🛑 Stopping Watch Monitor Service...
    python windows_service.py stop
    
    REM Wait for service to stop
    echo    Waiting for service to stop...
    timeout /t 5 /nobreak >nul
    
    REM Check if service stopped
    for /f "tokens=3" %%i in ('sc query "WatchMonitorService" ^| find "STATE"') do set "new_state=%%i"
    if /i "!new_state!" equ "STOPPED" (
        echo ✅ Service stopped successfully
    ) else (
        echo ⚠️  Service may still be stopping...
        timeout /t 5 /nobreak >nul
    )
    echo.
) else (
    echo ✅ Service is already stopped
    echo.
)

REM Remove the service
echo 🗑️  Removing Watch Monitor Service...
python windows_service.py remove

if %errorLevel% neq 0 (
    echo ❌ ERROR: Failed to remove service!
    echo.
    echo This might be due to:
    echo 1. Service is still running (try stopping it first)
    echo 2. Insufficient privileges
    echo 3. Service is in use by another process
    echo.
    echo You can also try removing it manually:
    echo   sc delete "WatchMonitorService"
    echo.
    pause
    exit /b 1
)

echo ✅ Service removed successfully!
echo.

REM Verify removal
timeout /t 2 /nobreak >nul
sc query "WatchMonitorService" >nul 2>&1
if %errorLevel% neq 0 (
    echo ✅ Verified: Service is no longer installed
) else (
    echo ⚠️  Service may still be in the process of being removed
    echo    This is normal and should complete shortly.
)

echo.
echo ========================================
echo   Uninstallation Complete!
echo ========================================
echo.
echo The Watch Monitor Service has been removed from your system.
echo.
echo What was removed:
echo • Windows Service registration
echo • Auto-start on boot configuration
echo • Service failure restart policies
echo.
echo What was NOT removed:
echo • Application files (main_production.py, etc.)
echo • Log files in the logs/ directory
echo • Configuration files (.env, etc.)
echo • Python dependencies
echo.
echo If you want to reinstall the service later:
echo   run install_service.bat as Administrator
echo.

REM Optional cleanup
set /p "choice=Would you like to clean up log files too? (y/N): "
if /i "!choice!" equ "y" (
    if exist "logs\" (
        echo.
        echo 🧹 Cleaning up log files...
        rmdir /s /q "logs" 2>nul
        if %errorLevel% equ 0 (
            echo ✅ Log files cleaned up
        ) else (
            echo ⚠️  Some log files may still be in use
        )
    ) else (
        echo 💡 No log files found to clean up
    )
)

echo.
echo Thank you for using Watch Monitor Service!
echo.
pause