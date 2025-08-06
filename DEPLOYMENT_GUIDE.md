# Watch Monitor Production Deployment Guide

## Table of Contents
1. [Prerequisites](#prerequisites)
2. [Quick Start](#quick-start)
3. [Windows Server Deployment](#windows-server-deployment)
4. [Configuration](#configuration)
5. [Running as Windows Service](#running-as-windows-service)
6. [Monitoring & Maintenance](#monitoring--maintenance)
7. [Troubleshooting](#troubleshooting)
8. [Security Best Practices](#security-best-practices)

## Prerequisites

### System Requirements
- **Windows Server 2016+** or **Windows 10+** 
- **Python 3.8+** (3.10+ recommended)
- **4GB RAM minimum** (8GB recommended)
- **10GB free disk space**
- **Stable internet connection**
- **Administrator privileges** (for service installation)

### Required Software
```powershell
# Check Python version
python --version

# Install required packages
pip install -r requirements.txt
```

## Quick Start

### 1. Clone or Download the Application
```powershell
# Option 1: Clone from repository
git clone <repository-url>
cd watch-monitor-rust/watch_monitor_refactored

# Option 2: Extract from ZIP
# Extract the provided ZIP file to desired location
```

### 2. Set Up Configuration
```powershell
# Copy the example environment file
copy .env.example .env

# Edit .env with your Discord webhook URLs
notepad .env
```

### 3. Configure Discord Webhooks
1. Open Discord and navigate to your server
2. Go to **Server Settings** → **Integrations** → **Webhooks**
3. Click **Create Webhook** for each watch site
4. Copy the webhook URL
5. Paste into corresponding variable in `.env` file

Example webhook URL format:
```
https://discord.com/api/webhooks/1234567890/AbCdEfGhIjKlMnOpQrStUvWxYz
```

### 4. Test Configuration
```powershell
# Validate configuration
python main_production.py --validate

# Run a single test cycle
python main_production.py --single
```

## Windows Server Deployment

### Step 1: Prepare the Server
```powershell
# Create application directory
mkdir C:\WatchMonitor
cd C:\WatchMonitor

# Copy application files
xcopy /E /I <source-path> C:\WatchMonitor

# Create logs directory
mkdir logs
```

### Step 2: Create Virtual Environment
```powershell
# Create virtual environment
python -m venv venv

# Activate virtual environment
.\venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Step 3: Configure Environment
```powershell
# Copy and edit configuration
copy .env.example .env
notepad .env

# Set production values in .env:
CHECK_INTERVAL_SECONDS=300  # 5 minutes
MAX_CONCURRENT_SCRAPERS=2   # Conservative for production
ENABLE_NOTIFICATIONS=true   # Enable Discord notifications
```

### Step 4: Run Initial Test
```powershell
# Test with virtual environment activated
.\venv\Scripts\activate
python main_production.py --validate
python main_production.py --single
```

## Running as Windows Service

### Option 1: Automatic Installation (Recommended)
```powershell
# Run as Administrator
cd C:\WatchMonitor

# Install the service
.\install_service.bat

# The script will:
# - Check for admin privileges
# - Validate Python installation
# - Install the service
# - Configure auto-restart on failure
```

### Option 2: Manual Installation
```powershell
# Run as Administrator
cd C:\WatchMonitor

# Install service
python windows_service.py install

# Start service
python windows_service.py start

# Check status
python windows_service.py status
```

### Service Management
```powershell
# Using the service manager script
.\service_manager.bat

# Or using command line:
# Start service
net start WatchMonitor

# Stop service
net stop WatchMonitor

# View service status
sc query WatchMonitor
```

## Configuration

### Environment Variables
All configuration is managed through environment variables in the `.env` file:

#### Required Settings
- `WORLDOFTIME_WEBHOOK_URL` - Discord webhook for World of Time
- `GRIMMEISSEN_WEBHOOK_URL` - Discord webhook for Grimmeissen
- `TROPICALWATCH_WEBHOOK_URL` - Discord webhook for Tropical Watch
- `JUWELIER_EXCHANGE_WEBHOOK_URL` - Discord webhook for Juwelier Exchange
- `WATCH_OUT_WEBHOOK_URL` - Discord webhook for Watch Out
- `RUESCHENBECK_WEBHOOK_URL` - Discord webhook for Rüschenbeck

#### Performance Tuning
```bash
# Production recommended values
CHECK_INTERVAL_SECONDS=300      # 5 minutes between checks
MAX_CONCURRENT_SCRAPERS=2       # Concurrent site scraping
MAX_CONCURRENT_DETAILS=5        # Concurrent detail pages per site
DETAIL_PAGE_DELAY=1.5           # Delay between detail fetches
REQUEST_TIMEOUT=15              # HTTP timeout in seconds
```

#### Advanced Settings
```bash
# Data retention
MAX_SEEN_ITEMS_PER_SITE=10000  # Track up to 10k watches per site
SESSION_HISTORY_RETENTION_DAYS=30  # Keep 30 days of history

# Feature flags
ENABLE_NOTIFICATIONS=true       # Send Discord notifications
ENABLE_DETAIL_SCRAPING=true    # Fetch detailed watch information
ENABLE_EXCHANGE_RATE_CONVERSION=true  # Convert USD to EUR
```

## Monitoring & Maintenance

### View Logs
```powershell
# View recent logs
type logs\watch_monitor.log

# Follow logs in real-time (PowerShell)
Get-Content logs\watch_monitor.log -Wait

# Check Windows Event Log
eventvwr.msc
# Navigate to: Windows Logs > Application > Filter by "WatchMonitor"
```

### Health Checks
```powershell
# Run health check
python main_production.py --health-check

# View statistics
python main_production.py --stats 7  # Last 7 days
```

### Scheduled Maintenance
Create a scheduled task for regular maintenance:

1. Open Task Scheduler (`taskschd.msc`)
2. Create Basic Task → "Watch Monitor Maintenance"
3. Trigger: Weekly
4. Action: Start a program
5. Program: `C:\WatchMonitor\maintenance.bat`

Example `maintenance.bat`:
```batch
@echo off
cd C:\WatchMonitor
python -c "from persistence import PersistenceManager; pm = PersistenceManager(); pm.cleanup_old_sessions()"
python main_production.py --stats 30 > logs\weekly_report.txt
```

## Troubleshooting

### Common Issues

#### 1. Service Won't Start
```powershell
# Check Python path
where python

# Verify virtual environment
C:\WatchMonitor\venv\Scripts\python.exe --version

# Check service logs
type logs\service.log

# Run in debug mode
python windows_service.py debug
```

#### 2. No Discord Notifications
```powershell
# Test webhook directly
python -c "from notifications import NotificationManager; import asyncio; asyncio.run(NotificationManager().test_webhook('YOUR_WEBHOOK_URL'))"

# Check configuration
python main_production.py --validate
```

#### 3. High Memory Usage
```powershell
# Clear old session data
python -c "from persistence import PersistenceManager; pm = PersistenceManager(); pm.cleanup_old_sessions(days=7)"

# Reduce concurrent scrapers in .env
SET MAX_CONCURRENT_SCRAPERS=1
```

#### 4. Rate Limiting Issues
```powershell
# Increase delays in .env
SET CHECK_INTERVAL_SECONDS=600  # 10 minutes
SET DETAIL_PAGE_DELAY=3.0       # 3 seconds between pages
```

### Debug Mode
Run the application in debug mode for detailed output:
```powershell
# Set log level to DEBUG
python main_production.py --log-level DEBUG --single

# Or for service debugging
python windows_service.py debug
```

## Security Best Practices

### 1. Protect Credentials
- **Never commit `.env` file to version control**
- Store webhook URLs securely
- Use Windows Credential Manager for sensitive data
- Regularly rotate webhook URLs

### 2. Network Security
- Configure Windows Firewall to allow only required outbound connections
- Use a dedicated service account with minimal privileges
- Enable Windows Defender real-time protection

### 3. File Permissions
```powershell
# Restrict access to configuration files
icacls .env /grant:r "%USERNAME%:(R)" /inheritance:r
icacls logs /grant:r "%USERNAME%:(M)" /inheritance:r
```

### 4. Monitoring Security
- Review logs regularly for suspicious activity
- Set up alerts for repeated failures
- Monitor outbound network traffic
- Keep Python and dependencies updated

### 5. Backup Strategy
```powershell
# Create backup script (backup.bat)
@echo off
set BACKUP_DIR=C:\Backups\WatchMonitor
set DATE=%date:~-4,4%%date:~-10,2%%date:~-7,2%
mkdir %BACKUP_DIR%\%DATE%
copy seen_watches.json %BACKUP_DIR%\%DATE%\
copy session_history.json %BACKUP_DIR%\%DATE%\
copy .env %BACKUP_DIR%\%DATE%\
echo Backup completed to %BACKUP_DIR%\%DATE%
```

## Performance Optimization

### Windows-Specific Optimizations
1. **Disable Windows Search indexing** for the application directory
2. **Add application directory to Windows Defender exclusions** (after security review)
3. **Use SSD storage** for application and data files
4. **Configure Windows Power Plan** to "High Performance"

### Application Tuning
```bash
# For high-volume monitoring
MAX_CONCURRENT_SCRAPERS=3
MAX_CONCURRENT_DETAILS=10
MAX_SEEN_ITEMS_PER_SITE=20000

# For resource-constrained servers
MAX_CONCURRENT_SCRAPERS=1
MAX_CONCURRENT_DETAILS=3
CHECK_INTERVAL_SECONDS=600
```

## Support and Updates

### Checking for Updates
```powershell
# Check current version
python -c "print(open('VERSION').read())"

# Update process
1. Stop the service: net stop WatchMonitor
2. Backup current installation
3. Copy new files (preserve .env and data files)
4. Run validation: python main_production.py --validate
5. Start service: net start WatchMonitor
```

### Getting Help
- Check logs in `logs/` directory
- Run health checks: `python main_production.py --health-check`
- Review this documentation
- Check Windows Event Log for service issues

## Appendix: Complete Setup Checklist

- [ ] Windows Server 2016+ or Windows 10+ installed
- [ ] Python 3.8+ installed and in PATH
- [ ] Application files copied to C:\WatchMonitor
- [ ] Virtual environment created and activated
- [ ] Dependencies installed via pip
- [ ] .env file created with webhook URLs
- [ ] Configuration validated
- [ ] Test cycle completed successfully
- [ ] Windows service installed
- [ ] Service starts automatically
- [ ] Logs being generated
- [ ] Discord notifications working
- [ ] Backup strategy implemented
- [ ] Monitoring alerts configured
- [ ] Documentation reviewed by team

## Production Launch Checklist

Before going live:
1. ✅ All webhook URLs configured and tested
2. ✅ Service installed and auto-starting
3. ✅ Logs rotating properly
4. ✅ Monitoring dashboard accessible
5. ✅ Backup script scheduled
6. ✅ Team trained on troubleshooting
7. ✅ Incident response plan documented
8. ✅ Change management process defined
9. ✅ Performance baseline established
10. ✅ Security review completed

---

**Last Updated**: 2024
**Version**: 2.0.0
**Status**: Production Ready