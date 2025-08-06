@echo off
REM Reset seen watches and test notifications
REM This is useful for testing if notifications work

echo ========================================
echo Watch Monitor - Reset and Test
echo ========================================
echo.

echo This will:
echo 1. Reset seen watches for testing
echo 2. Run one monitoring cycle
echo 3. Send notifications for all watches found
echo.

set /p confirm="Continue? (Y/N): "
if /i not "%confirm%"=="Y" (
    echo Cancelled.
    exit /b
)

echo.
echo Resetting seen watches and testing...
python main_production.py --test-notifications

echo.
echo ========================================
echo Test complete! Check Discord for notifications.
echo ========================================
pause