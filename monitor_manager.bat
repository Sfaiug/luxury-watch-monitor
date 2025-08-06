@echo off
REM Watch Monitor Manager - Interactive menu for managing the monitor

:menu
cls
echo ============================================
echo        WATCH MONITOR MANAGER
echo ============================================
echo.
echo 1. Run continuous monitoring
echo 2. Run single cycle
echo 3. Test notifications (reset and test)
echo 4. Reset Watch Out seen watches
echo 5. Reset Tropical Watch seen watches  
echo 6. Reset ALL seen watches
echo 7. Show statistics
echo 8. Validate configuration
echo 9. Create .env template
echo 10. Exit
echo.
echo ============================================
set /p choice="Enter your choice (1-10): "

if "%choice%"=="1" goto continuous
if "%choice%"=="2" goto single
if "%choice%"=="3" goto test_notifications
if "%choice%"=="4" goto reset_watchout
if "%choice%"=="5" goto reset_tropical
if "%choice%"=="6" goto reset_all
if "%choice%"=="7" goto stats
if "%choice%"=="8" goto validate
if "%choice%"=="9" goto create_env
if "%choice%"=="10" goto exit

echo Invalid choice. Please try again.
pause
goto menu

:continuous
echo.
echo Starting continuous monitoring...
echo Press Ctrl+C to stop
echo.
python main_production.py
pause
goto menu

:single
echo.
echo Running single monitoring cycle...
python main_production.py --single
pause
goto menu

:test_notifications
echo.
echo Testing notifications with fresh detection...
python main_production.py --test-notifications
pause
goto menu

:reset_watchout
echo.
echo Resetting Watch Out seen watches...
python main_production.py --reset-seen watch_out
echo.
echo Done! Run a single cycle to test.
pause
goto menu

:reset_tropical
echo.
echo Resetting Tropical Watch seen watches...
python main_production.py --reset-seen tropicalwatch
echo.
echo Done! Run a single cycle to test.
pause
goto menu

:reset_all
echo.
set /p confirm="Reset ALL seen watches? This cannot be undone. (Y/N): "
if /i "%confirm%"=="Y" (
    python main_production.py --reset-seen
    echo.
    echo All seen watches have been reset!
) else (
    echo Cancelled.
)
pause
goto menu

:stats
echo.
set /p days="Enter number of days for statistics (default 7): "
if "%days%"=="" set days=7
python main_production.py --stats %days%
pause
goto menu

:validate
echo.
echo Validating configuration and testing webhooks...
python main_production.py --validate
pause
goto menu

:create_env
echo.
echo Creating .env.example template...
python main_production.py --create-env
echo.
echo Template created! Copy it to .env and add your webhook URLs.
pause
goto menu

:exit
echo.
echo Goodbye!
exit /b