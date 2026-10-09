"""Scraper implementations for watch monitor."""

from .base import BaseScraper
from .worldoftime import WorldOfTimeScraper
from .grimmeissen import GrimmeissenScraper
from .tropicalwatch import TropicalWatchScraper
from .juwelier_exchange import JuwelierExchangeScraper
from .watch_out import WatchOutScraper
from .rueschenbeck import RueschenbeckScraper
from .bachmann_scher import BachmannScherScraper

__all__ = [
    "BaseScraper",
    "WorldOfTimeScraper", 
    "GrimmeissenScraper",
    "TropicalWatchScraper",
    "JuwelierExchangeScraper", 
    "WatchOutScraper",
    "RueschenbeckScraper",
    "BachmannScherScraper"
]