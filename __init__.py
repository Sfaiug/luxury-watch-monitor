"""Watch Monitor - Luxury Watch Monitoring System."""

from .monitor import WatchMonitor
from .models import WatchData, ScrapingSession
from .config import APP_CONFIG, SITE_CONFIGS

__version__ = "2.0.0"
__all__ = ["WatchMonitor", "WatchData", "ScrapingSession", "APP_CONFIG", "SITE_CONFIGS"]