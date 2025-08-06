@echo off
REM Fix DNS issues for Tropical Watch and other sites
REM Run as Administrator for best results

echo ==========================================
echo    DNS ISSUE FIX FOR WATCH MONITOR
echo ==========================================
echo.

echo This script will help fix DNS resolution issues.
echo.
echo Current issues detected:
echo - tropicalwatch.com DNS resolution failing
echo.

:menu
echo Select an option:
echo 1. Flush DNS cache
echo 2. Test DNS resolution
echo 3. Add hosts file entry (requires admin)
echo 4. Use Google DNS
echo 5. Check Windows Firewall
echo 6. Exit
echo.
set /p choice="Enter choice (1-6): "

if "%choice%"=="1" goto flush_dns
if "%choice%"=="2" goto test_dns
if "%choice%"=="3" goto add_hosts
if "%choice%"=="4" goto google_dns
if "%choice%"=="5" goto check_firewall
if "%choice%"=="6" goto exit

:flush_dns
echo.
echo Flushing DNS cache...
ipconfig /flushdns
echo.
echo DNS cache flushed successfully!
echo.
pause
goto menu

:test_dns
echo.
echo Testing DNS resolution...
echo.
echo Testing tropicalwatch.com:
nslookup tropicalwatch.com
echo.
echo Testing with Google DNS:
nslookup tropicalwatch.com 8.8.8.8
echo.
pause
goto menu

:add_hosts
echo.
echo Adding hosts file entry (requires admin rights)...
echo.
echo The IP for tropicalwatch.com is typically: 143.204.109.7
echo.
set /p confirm="Add this entry to hosts file? (Y/N): "
if /i "%confirm%"=="Y" (
    echo 143.204.109.7 tropicalwatch.com >> C:\Windows\System32\drivers\etc\hosts
    echo 143.204.109.7 www.tropicalwatch.com >> C:\Windows\System32\drivers\etc\hosts
    echo.
    echo Hosts file updated! Flush DNS cache now.
    ipconfig /flushdns
) else (
    echo Cancelled.
)
pause
goto menu

:google_dns
echo.
echo To use Google DNS:
echo.
echo 1. Open Network Settings
echo 2. Change adapter options
echo 3. Right-click your connection -> Properties
echo 4. Select Internet Protocol Version 4 (TCP/IPv4)
echo 5. Click Properties
echo 6. Use the following DNS server addresses:
echo    Preferred: 8.8.8.8
echo    Alternate: 8.8.4.4
echo.
echo Or use Cloudflare DNS:
echo    Preferred: 1.1.1.1
echo    Alternate: 1.0.0.1
echo.
pause
goto menu

:check_firewall
echo.
echo Checking Windows Firewall...
echo.
netsh advfirewall show allprofiles
echo.
echo To allow Python through firewall:
netsh advfirewall firewall add rule name="Python Watch Monitor" dir=out action=allow program="%PYTHONPATH%" enable=yes
echo.
pause
goto menu

:exit
exit /b