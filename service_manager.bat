@echo off
REM Watch Monitor Service Manager
REM Easy interface for managing the Watch Monitor Windows Service
REM Requires Administrator privileges for most operations

setlocal EnableDelayedExpansion

:main_menu
cls
echo.
echo ========================================
echo     Watch Monitor Service Manager
echo ========================================
echo.

REM Check if service exists
sc query "WatchMonitorService" >nul 2>&1
if %errorLevel% neq 0 (
    echo ❌ Watch Monitor Service is not installed
    echo.
    echo Available options:
    echo.
    echo [I] Install Service
    echo [Q] Quit
    echo.
    set /p "choice=Select an option: "
    
    if /i "!choice!" equ "I" goto install_service
    if /i "!choice!" equ "Q" exit /b 0
    
    echo Invalid option. Please try again.
    timeout /t 2 /nobreak >nul
    goto main_menu
)

REM Get service status
for /f "tokens=3" %%i in ('sc query "WatchMonitorService" ^| find "STATE"') do set "service_state=%%i"
for /f "tokens=2" %%i in ('sc qc "WatchMonitorService" ^| find "START_TYPE"') do set "start_type=%%i"

echo 📊 Service Status: !service_state!
echo 🔧 Start Type: !start_type!
echo.

REM Show appropriate menu based on service state
if /i "!service_state!" equ "RUNNING" (
    echo ✅ Service is currently RUNNING
    echo.
    echo Available options:
    echo.
    echo [S] Stop Service
    echo [R] Restart Service
    echo [L] View Logs
    echo [T] View Status Details
    echo [D] Debug Mode
    echo [U] Uninstall Service
    echo [Q] Quit
) else if /i "!service_state!" equ "STOPPED" (
    echo ⏸️  Service is currently STOPPED
    echo.
    echo Available options:
    echo.
    echo [1] Start Service
    echo [L] View Logs
    echo [T] View Status Details
    echo [D] Debug Mode
    echo [U] Uninstall Service
    echo [Q] Quit
) else (
    echo ⚠️  Service is in state: !service_state!
    echo.
    echo Available options:
    echo.
    echo [T] View Status Details
    echo [D] Debug Mode
    echo [U] Uninstall Service
    echo [Q] Quit
)

echo.
set /p "choice=Select an option: "

REM Handle user choice
if /i "!choice!" equ "1" goto start_service
if /i "!choice!" equ "S" goto stop_service
if /i "!choice!" equ "R" goto restart_service
if /i "!choice!" equ "L" goto view_logs
if /i "!choice!" equ "T" goto view_status
if /i "!choice!" equ "D" goto debug_mode
if /i "!choice!" equ "U" goto uninstall_service
if /i "!choice!" equ "I" goto install_service
if /i "!choice!" equ "Q" exit /b 0

echo Invalid option. Please try again.
timeout /t 2 /nobreak >nul
goto main_menu

:start_service
echo.
echo 🚀 Starting Watch Monitor Service...
python windows_service.py start

if %errorLevel% equ 0 (
    echo ✅ Service started successfully!
) else (
    echo ❌ Failed to start service
    echo Check the logs or try debug mode for more information
)

echo.
pause
goto main_menu

:stop_service
echo.
echo 🛑 Stopping Watch Monitor Service...
python windows_service.py stop

if %errorLevel% equ 0 (
    echo ✅ Service stopped successfully!
) else (
    echo ❌ Failed to stop service
)

echo.
pause
goto main_menu

:restart_service
echo.
echo 🔄 Restarting Watch Monitor Service...
echo.
echo Stopping service...
python windows_service.py stop
timeout /t 3 /nobreak >nul

echo Starting service...
python windows_service.py start

if %errorLevel% equ 0 (
    echo ✅ Service restarted successfully!
) else (
    echo ❌ Failed to restart service
)

echo.
pause
goto main_menu

:view_logs
echo.
echo 📋 Watch Monitor Logs
echo ==================
echo.

REM Check for different log locations
if exist "logs\windows_service.log" (
    echo 🪟 Windows Service Log (last 20 lines):
    echo ---------------------------------------
    powershell -Command "Get-Content 'logs\windows_service.log' -Tail 20"
    echo.
)

if exist "logs\watch_monitor_service.log" (
    echo 📊 Application Log (last 20 lines):
    echo ----------------------------------
    powershell -Command "Get-Content 'logs\watch_monitor_service.log' -Tail 20"
    echo.
)

if not exist "logs\" (
    echo ⚠️  No log directory found
    echo The service may not have been started yet, or logs are disabled.
    echo.
)

echo 💡 Pro Tip: Check Windows Event Viewer ^> Application for service events
echo.
pause
goto main_menu

:view_status
echo.
echo 📊 Detailed Service Status
echo =========================
echo.

sc query "WatchMonitorService"
echo.

sc qc "WatchMonitorService"
echo.

REM Show process information if running
for /f "tokens=2" %%i in ('tasklist /svc /fi "services eq WatchMonitorService" /fo csv ^| find "WatchMonitorService"') do (
    set "process_name=%%i"
    echo Process: !process_name!
)

echo.
pause
goto main_menu

:debug_mode
echo.
echo 🐛 Starting Debug Mode
echo =====================
echo.
echo This will run the Watch Monitor interactively so you can see
echo what's happening. Press Ctrl+C to stop when done.
echo.
echo Note: If the service is running, you should stop it first
echo to avoid conflicts.
echo.

if /i "!service_state!" equ "RUNNING" (
    set /p "choice=Service is running. Stop it first? (Y/n): "
    if /i "!choice!" neq "n" (
        python windows_service.py stop
        timeout /t 3 /nobreak >nul
    )
)

echo.
echo Starting debug mode...
echo.
python windows_service.py debug

echo.
echo Debug mode ended.
pause
goto main_menu

:install_service
echo.
echo 🔧 Installing Watch Monitor Service...
echo.

REM Check for install script
if exist "install_service.bat" (
    echo Found install_service.bat - launching installer...
    echo.
    call install_service.bat
) else (
    echo install_service.bat not found. Installing directly...
    python windows_service.py install
)

echo.
pause
goto main_menu

:uninstall_service
echo.
echo 🗑️  Uninstalling Watch Monitor Service...
echo.

REM Check for uninstall script
if exist "uninstall_service.bat" (
    echo Found uninstall_service.bat - launching uninstaller...
    echo.
    call uninstall_service.bat
) else (
    echo uninstall_service.bat not found. Uninstalling directly...
    echo.
    set /p "choice=Are you sure you want to uninstall the service? (y/N): "
    if /i "!choice!" equ "y" (
        python windows_service.py stop
        timeout /t 3 /nobreak >nul
        python windows_service.py remove
    )
)

echo.
pause
goto main_menu