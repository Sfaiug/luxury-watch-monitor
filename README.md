# Watch Monitor - Luxury Watch Price Tracker

A production-ready Python application that monitors luxury watch retailers and sends Discord notifications for new listings. Supports automatic USD to EUR conversion for international sites.

## 🌟 Features

- **6 Luxury Watch Retailers Monitored**:
  - World of Time (Germany)
  - Grimmeissen (Germany)
  - Tropical Watch (USA) - with USD→EUR conversion
  - Juwelier Exchange (Germany)
  - Watch Out (Germany)
  - Rüschenbeck (Germany)

- **Smart Notifications**: Discord webhooks with rich embeds showing watch details
- **Currency Conversion**: Automatic USD to EUR conversion with live exchange rates
- **Concurrent Scraping**: Efficient parallel processing with rate limiting
- **Windows Service**: Runs as a Windows service with auto-start and recovery
- **Production Ready**: Comprehensive error handling, logging, and monitoring

## 📦 Quick Start

### Prerequisites
- Python 3.8+ (3.10+ recommended)
- Windows Server 2016+ or Windows 10+
- Discord webhook URLs

### Installation

1. **Clone the repository**:
```bash
git clone https://github.com/Sfaiug/luxury-watch-monitor.git
cd luxury-watch-monitor
```

2. **Create virtual environment**:
```bash
python -m venv venv
.\venv\Scripts\activate  # Windows
source venv/bin/activate  # Mac/Linux
```

3. **Install dependencies**:
```bash
pip install -r requirements.txt
```

4. **Configure Discord webhooks**:
```bash
copy .env.example .env
# Edit .env and add your Discord webhook URLs
```

### Running the Application

#### Single monitoring cycle:
```bash
python main_production.py --single
```

#### Continuous monitoring:
```bash
python main_production.py
```

#### Install as Windows Service:
```bash
# Run as Administrator
install_service.bat
```

## 🐳 Docker Support

Build and run with Docker:
```bash
docker build -t watch-monitor .
docker run -v ./.env:/app/.env watch-monitor
```

Or use Docker Compose:
```bash
docker-compose up -d
```

## 🔧 Configuration

All configuration is managed through environment variables in `.env`:

```ini
# Discord Webhooks (Required)
WORLDOFTIME_WEBHOOK_URL=https://discord.com/api/webhooks/...
GRIMMEISSEN_WEBHOOK_URL=https://discord.com/api/webhooks/...
TROPICALWATCH_WEBHOOK_URL=https://discord.com/api/webhooks/...
# ... etc

# Monitoring Settings
CHECK_INTERVAL_SECONDS=300  # 5 minutes
MAX_CONCURRENT_SCRAPERS=2   # Conservative for production
```

## 📊 Architecture

```
watch-monitor/
├── scrapers/           # Site-specific scraper implementations
│   ├── base.py        # Abstract base scraper
│   ├── worldoftime.py
│   ├── grimmeissen.py
│   ├── tropicalwatch.py  # Includes USD→EUR conversion
│   └── ...
├── config.py          # Configuration management
├── models.py          # Data models
├── monitor.py         # Main orchestrator
├── notifications.py   # Discord notification handler
├── persistence.py     # Data persistence layer
├── main_production.py # Production entry point
└── windows_service.py # Windows service wrapper
```

## 🚀 Production Deployment

### Windows Server Deployment

1. **Copy application** to `C:\WatchMonitor`
2. **Configure webhooks** in `.env`
3. **Install service** (as Administrator):
   ```cmd
   install_service.bat
   ```
4. **Service management**:
   ```cmd
   service_manager.bat  # Interactive management
   net start WatchMonitor  # Start service
   net stop WatchMonitor   # Stop service
   ```

### Features for Production

- **Auto-restart**: Service restarts automatically on failure
- **Logging**: Comprehensive logging to files and Windows Event Log
- **Rate limiting**: Respects target site limits
- **Error recovery**: Exponential backoff and retry logic
- **Health checks**: Built-in monitoring and statistics

## 📈 Statistics & Monitoring

View monitoring statistics:
```bash
python main_production.py --stats 7  # Last 7 days
```

Health check:
```bash
python main_production.py --health-check
```

## 🛠️ Development

### Running Tests
```bash
scripts/test.sh
```

### Code Structure
- **Inheritance-based scrapers**: All scrapers inherit from `BaseScraper`
- **Async/await**: Modern async Python for concurrent operations
- **Type hints**: Full type annotations for better IDE support
- **Dataclasses**: Clean data models with validation

## 📝 License

MIT License - see LICENSE file for details

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 🐛 Issues

Report issues at: https://github.com/Sfaiug/luxury-watch-monitor/issues

## 📞 Support

For support, please open an issue on GitHub.

---

**Note**: This application is for personal use only. Please respect the terms of service of the monitored websites and implement appropriate rate limiting.