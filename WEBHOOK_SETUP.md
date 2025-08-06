# Discord Webhook Setup Guide

## 🎯 Quick Start

### 1. Create Discord Webhooks

For each Discord channel where you want notifications:

1. **Open Discord** → Go to your server
2. **Right-click the channel** → Select "Edit Channel"
3. **Go to "Integrations"** → Click "Webhooks"
4. **Click "New Webhook"** → Give it a name (e.g., "Watch Out Monitor")
5. **Copy the Webhook URL** → Click "Copy Webhook URL"

### 2. Configure Environment Variables

#### Option A: Using .env file (Recommended)

1. Create a `.env` file in the project root:
```bash
cp .env.example .env
```

2. Edit `.env` and paste your webhook URLs:
```ini
# Watch Out webhook
WATCH_OUT_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_WEBHOOK_HERE

# Tropical Watch webhook  
TROPICALWATCH_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_WEBHOOK_HERE

# Add other sites as needed...
WORLDOFTIME_WEBHOOK_URL=
GRIMMEISSEN_WEBHOOK_URL=
JUWELIER_EXCHANGE_WEBHOOK_URL=
RUESCHENBECK_WEBHOOK_URL=
```

#### Option B: Using System Environment Variables (Windows)

1. Open Command Prompt as Administrator
2. Set environment variables:
```cmd
setx WATCH_OUT_WEBHOOK_URL "https://discord.com/api/webhooks/YOUR_WEBHOOK_HERE"
setx TROPICALWATCH_WEBHOOK_URL "https://discord.com/api/webhooks/YOUR_WEBHOOK_HERE"
```

3. Restart your terminal/command prompt

## 🧪 Testing Notifications

### Test Individual Sites

```bash
# Test Watch Out notifications
python test_notifications.py watch_out --reset

# Test Tropical Watch notifications  
python test_notifications.py tropicalwatch --reset

# Test both
python test_notifications.py --reset
```

### Test with Fresh Detection

To ensure notifications work with a clean slate:

```bash
# Reset ALL seen watches and test
python main_production.py --test-notifications
```

This will:
1. Clear all seen watches
2. Run one monitoring cycle
3. Send notifications for ALL watches found
4. Show you exactly what was sent

### Test Specific Sites Only

```bash
# Reset only Watch Out and test
python main_production.py --reset-seen watch_out --single

# Reset only Tropical Watch and test
python main_production.py --reset-seen tropicalwatch --single
```

## 🔍 Troubleshooting

### No Notifications Being Sent?

1. **Check webhook configuration:**
```bash
python main_production.py --validate
```

2. **Check if watches are marked as "seen":**
```bash
python test_notifications.py
```
This shows how many watches are already tracked.

3. **Reset seen watches for fresh detection:**
```bash
# Reset specific site
python main_production.py --reset-seen watch_out

# Reset all sites
python main_production.py --reset-seen
```

4. **Enable debug logging:**
```bash
python main_production.py --single --log-level DEBUG
```

### Common Issues

#### Issue: "Found X watches but 0 new watches"
**Solution:** Watches are already in `seen_watches.json`. Use `--reset-seen` to clear them.

```bash
python main_production.py --reset-seen watch_out tropicalwatch --single
```

#### Issue: "No webhook configured for site"
**Solution:** Check your `.env` file has the correct variable name:
- `WATCH_OUT_WEBHOOK_URL` (not WATCHOUT_WEBHOOK_URL)
- `TROPICALWATCH_WEBHOOK_URL` (not TROPICAL_WATCH_WEBHOOK_URL)

#### Issue: Discord rate limiting (429 errors)
**Solution:** The script automatically handles rate limits with 1-second delays between messages.

#### Issue: Network/DNS errors
**Solution:** These are usually temporary. The script will retry on the next cycle.

## 📊 Monitoring Dashboard

View current status:
```bash
# Show statistics for last 7 days
python main_production.py --stats 7

# Health check
python main_production.py --health-check
```

## 🚀 Production Deployment

### Running Continuously

```bash
# Basic continuous monitoring
python main_production.py

# With auto-restart on failure
python main_production.py --auto-restart

# With logging to file
python main_production.py --log-file logs/monitor.log
```

### Windows Service Installation

```bash
# Install as Windows service
python windows_service.py install

# Start the service
python windows_service.py start

# Check service status
python windows_service.py status
```

## 📝 Webhook URL Format

Discord webhook URLs should look like:
```
https://discord.com/api/webhooks/[WEBHOOK_ID]/[WEBHOOK_TOKEN]
```

Example:
```
https://discord.com/api/webhooks/1234567890123456789/abcdefghijklmnopqrstuvwxyz1234567890
```

## 🔐 Security Notes

1. **Never commit webhook URLs to Git**
   - Keep them in `.env` (which is gitignored)
   - Or use system environment variables

2. **Webhook permissions are limited**
   - Webhooks can only post messages
   - They cannot read messages or access other channels

3. **Rotate webhooks if compromised**
   - Delete the old webhook in Discord
   - Create a new one and update your configuration

## 📱 Discord Mobile Notifications

To ensure you get mobile notifications:

1. **Server Settings** → Enable notifications for the webhook channel
2. **User Settings** → Enable push notifications
3. **Channel Settings** → Set notification level to "All Messages"

## 🆘 Need Help?

1. **Check logs:** Look for ERROR or WARNING messages
2. **Test manually:** Use `test_notifications.py` script
3. **Validate setup:** Run `python main_production.py --validate`
4. **Debug mode:** Add `--log-level DEBUG` for detailed output

## Example Full Setup (Windows)

```bash
# 1. Create .env from template
copy .env.example .env

# 2. Edit .env with your webhook URLs
notepad .env

# 3. Test the setup
python main_production.py --validate

# 4. Reset seen watches for testing
python main_production.py --reset-seen

# 5. Run a test cycle
python main_production.py --single

# 6. If notifications work, run continuously
python main_production.py
```