# Migration Guide: Original to Refactored Version

This guide helps you migrate from the original `watch_monitor.py` to the refactored modular version.

## 🔄 Key Changes

### 1. **Environment Variables Instead of Hardcoded Webhooks**

**Before (CRITICAL SECURITY ISSUE):**
```python
"webhook": "https://discord.com/api/webhooks/1356956538190823534/GMUibI4sDu9I515zDvxyC0cqkFiXC_D4yh89L36WsRIdIzSlTmtFx4LTtxxsodYBSqXB"
```

**After:**
```python
"webhook_env_var": "WORLDOFTIME_WEBHOOK_URL"
```

### 2. **Modular Architecture**

**Before:** Single 1,480-line file
**After:** Organized into logical modules:
- `config.py` - Configuration
- `models.py` - Data structures
- `scrapers/` - Site-specific logic
- `persistence.py` - Data storage
- `notifications.py` - Discord integration

### 3. **Async/Concurrent Operation**

**Before:** Sequential scraping with blocking sleep
**After:** Concurrent scraping with asyncio

## 📦 Migration Steps

### Step 1: Backup Existing Data

```bash
# Backup your seen watches data
cp seen_watches.json seen_watches_backup.json
```

### Step 2: Set Up Environment

1. Create a new directory:
```bash
mkdir watch_monitor_new
cd watch_monitor_new
```

2. Copy the refactored code:
```bash
cp -r /path/to/watch_monitor_refactored/* .
```

3. Create virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate
```

4. Install dependencies:
```bash
pip install -r requirements.txt
```

### Step 3: Configure Discord Webhooks

1. Extract webhook URLs from old config:
```python
# From old watch_monitor.py CONFIG dictionary
worldoftime_webhook = "https://discord.com/api/webhooks/..."
grimmeissen_webhook = "https://discord.com/api/webhooks/..."
# etc...
```

2. Create `.env` file:
```bash
cp .env.example .env
```

3. Add your webhook URLs to `.env`:
```
WORLDOFTIME_WEBHOOK_URL=https://discord.com/api/webhooks/...
GRIMMEISSEN_WEBHOOK_URL=https://discord.com/api/webhooks/...
# etc...
```

### Step 4: Migrate Seen Watches Data

The data format is compatible, just copy the file:
```bash
cp /path/to/old/seen_watches.json .
```

### Step 5: Test Configuration

```bash
# Validate webhooks and configuration
python main.py --validate

# Run a single test cycle
python main.py --single --log-level DEBUG
```

### Step 6: Implement Missing Scrapers

The refactored version includes only WorldOfTime scraper as an example. You need to create the others:

1. Use the original scraper functions as reference
2. Create new files in `scrapers/` directory
3. Follow the pattern in `scrapers/worldoftime.py`

Example for Grimmeissen:
```python
# scrapers/grimmeissen.py
from scrapers.base import BaseScraper
from models import WatchData
from utils import parse_price, parse_year, parse_condition

class GrimmeissenScraper(BaseScraper):
    async def _extract_watches(self, soup):
        # Port logic from original scrape_grimmeissen function
        watches = []
        # ... implementation
        return watches
```

### Step 7: Update Monitor Registry

In `monitor.py`, uncomment and import your scrapers:
```python
from scrapers.grimmeissen import GrimmeissenScraper
from scrapers.tropicalwatch import TropicalWatchScraper
# ... etc

SCRAPER_CLASSES = {
    "worldoftime": WorldOfTimeScraper,
    "grimmeissen": GrimmeissenScraper,
    "tropicalwatch": TropicalWatchScraper,
    # ... etc
}
```

## 🔧 Configuration Mapping

### Old Configuration → New Configuration

| Old Config | New Location | Notes |
|------------|--------------|-------|
| `CONFIG["worldoftime"]["webhook"]` | Environment: `WORLDOFTIME_WEBHOOK_URL` | Security improvement |
| `CONFIG["seen_watches_file"]` | `config.py`: `APP_CONFIG.seen_watches_file` | Same default |
| `CONFIG["check_interval_seconds"]` | `config.py`: `APP_CONFIG.check_interval_seconds` | Same default |
| `CONFIG["user_agent"]` | `config.py`: `APP_CONFIG.user_agent` | Same value |
| Site-specific config | `config.py`: `SITE_CONFIGS` | Better organization |

## 🚀 Running the Application

### Old Way:
```bash
python watch_monitor.py
```

### New Way:
```bash
# Continuous monitoring (same behavior)
python main.py

# With options
python main.py --single              # Run once
python main.py --validate           # Test configuration
python main.py --stats 7            # View statistics
python main.py --log-level DEBUG    # Debug mode
```

## ⚠️ Important Notes

1. **Test First**: Always run with `--single` flag first to verify everything works

2. **Webhook Security**: Never commit `.env` file to version control

3. **Backwards Compatibility**: The `seen_watches.json` format is preserved

4. **Performance**: The new version is faster due to concurrent scraping

5. **Logging**: Uses proper logging instead of print statements

## 🆘 Troubleshooting

### "No webhook configured" Warning
- Ensure `.env` file exists and contains webhook URLs
- Check environment variable names match exactly
- On Windows, you might need to set variables differently

### "No scraper implementation found"
- You need to create scraper classes for sites other than WorldOfTime
- Follow the example in `scrapers/worldoftime.py`

### Import Errors
- Ensure you're in the virtual environment: `source venv/bin/activate`
- Check all dependencies installed: `pip install -r requirements.txt`

### Seen Watches Not Working
- Verify `seen_watches.json` was copied correctly
- Check file permissions
- Look for any JSON parsing errors in logs

## 📝 Benefits After Migration

✅ **Security**: No hardcoded credentials
✅ **Performance**: Concurrent scraping, faster execution
✅ **Reliability**: Proper error handling and retries
✅ **Maintainability**: Modular code, easier to update
✅ **Monitoring**: Session tracking and statistics
✅ **Testing**: Comprehensive test suite included
✅ **Logging**: Professional logging with context

## 🔗 Quick Reference

| Task | Old Command | New Command |
|------|-------------|-------------|
| Run monitor | `python watch_monitor.py` | `python main.py` |
| Check status | Check prints | `python main.py --stats 7` |
| Debug issues | Add print statements | `python main.py --log-level DEBUG` |
| Test changes | Run and wait | `python main.py --single` |

Remember to always test thoroughly before deploying to production!