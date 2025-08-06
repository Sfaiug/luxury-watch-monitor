"""Main monitor orchestrator for watch monitor application."""

import asyncio
import signal
from typing import Dict, List, Set, Optional, Type
import aiohttp

from config import APP_CONFIG, SITE_CONFIGS, SiteConfig
from models import ScrapingSession, WatchData
from persistence import PersistenceManager
from notifications import NotificationManager
from logging_config import setup_logging, PerformanceLogger
from scrapers.base import BaseScraper

# Import all scraper implementations
from scrapers.worldoftime import WorldOfTimeScraper
from scrapers.grimmeissen import GrimmeissenScraper
from scrapers.tropicalwatch import TropicalWatchScraper
from scrapers.juwelier_exchange import JuwelierExchangeScraper
from scrapers.watch_out import WatchOutScraper
from scrapers.rueschenbeck import RueschenbeckScraper


# Map site keys to scraper classes
SCRAPER_CLASSES: Dict[str, Type[BaseScraper]] = {
    "worldoftime": WorldOfTimeScraper,
    "grimmeissen": GrimmeissenScraper,
    "tropicalwatch": TropicalWatchScraper,
    "juwelier_exchange": JuwelierExchangeScraper,
    "watch_out": WatchOutScraper,
    "rueschenbeck": RueschenbeckScraper,
}


class WatchMonitor:
    """Main orchestrator for the watch monitoring system."""
    
    def __init__(self, log_level: str = "INFO", log_file: Optional[str] = None):
        """
        Initialize the watch monitor.
        
        Args:
            log_level: Logging level
            log_file: Optional log file path
        """
        # Set up logging
        self.logger = setup_logging(log_level, log_file)
        
        # Initialize components
        self.persistence = PersistenceManager(self.logger)
        self.session: Optional[aiohttp.ClientSession] = None
        self.notification_manager: Optional[NotificationManager] = None
        
        # State
        self.seen_items: Dict[str, Set[str]] = {}
        self.scrapers: Dict[str, BaseScraper] = {}
        self.running = False
        self.shutdown_event = asyncio.Event()
        
        # Set up signal handlers
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)
    
    def _handle_shutdown(self, signum, frame):
        """Handle shutdown signals gracefully."""
        self.logger.info("Shutdown signal received")
        self.running = False
        self.shutdown_event.set()
    
    async def initialize(self):
        """Initialize async components."""
        # Create aiohttp session with connection pooling limits
        connector = aiohttp.TCPConnector(
            limit=20,  # Total connection pool size
            limit_per_host=5,  # Max connections per host
            ttl_dns_cache=300,  # DNS cache TTL (5 minutes)
            use_dns_cache=True,
            enable_cleanup_closed=True  # Clean up closed connections
        )
        
        timeout = aiohttp.ClientTimeout(
            total=APP_CONFIG.request_timeout,
            connect=10,  # Connection timeout
            sock_read=APP_CONFIG.request_timeout
        )
        
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={'User-Agent': APP_CONFIG.user_agent}
        )
        
        # Initialize notification manager
        self.notification_manager = NotificationManager(self.session, self.logger)
        
        # Load seen items
        self.seen_items = self.persistence.load_seen_items()
        
        # Initialize scrapers
        for site_key, site_config in SITE_CONFIGS.items():
            scraper_class = SCRAPER_CLASSES.get(site_key)
            if scraper_class:
                scraper = scraper_class(site_config, self.session, self.logger)
                
                # Set seen IDs for the scraper
                site_seen_ids = self.seen_items.get(site_key, set())
                scraper.set_seen_ids(site_seen_ids)
                
                self.scrapers[site_key] = scraper
            else:
                self.logger.warning(f"No scraper implementation found for {site_key}")
        
        self.logger.info("Watch monitor initialized successfully")
    
    async def cleanup(self):
        """Clean up resources."""
        if self.session:
            await self.session.close()
        
        # Save final state
        self.persistence.save_seen_items(self.seen_items)
        
        self.logger.info("Watch monitor cleaned up")
    
    async def run_monitoring_cycle(self) -> ScrapingSession:
        """
        Run a single monitoring cycle across all sites.
        
        Returns:
            ScrapingSession with results
        """
        session = ScrapingSession()
        
        with PerformanceLogger(self.logger, "monitoring cycle"):
            # Scrape sites concurrently with semaphore control
            semaphore = asyncio.Semaphore(APP_CONFIG.max_concurrent_scrapers)
            
            async def scrape_site_with_semaphore(site_key: str, scraper: BaseScraper):
                async with semaphore:
                    return await self._scrape_single_site(site_key, scraper, session)
            
            # Create tasks for all sites
            tasks = []
            for site_key, scraper in self.scrapers.items():
                task = scrape_site_with_semaphore(site_key, scraper)
                tasks.append(task)
            
            # Wait for all to complete
            await asyncio.gather(*tasks)
            
            # Finalize session
            session.finalize()
            
            # Save session history
            self.persistence.save_session(session)
            
            # Log summary
            self.logger.info(
                f"Monitoring cycle complete: "
                f"{session.total_new_watches} new watches found, "
                f"{session.notifications_sent} notifications sent"
            )
        
        return session
    
    async def _scrape_single_site(
        self,
        site_key: str,
        scraper: BaseScraper,
        session: ScrapingSession
    ):
        """Scrape a single site and update session."""
        try:
            self.logger.info(f"Starting scrape for {site_key}")
            
            # Scrape the site
            new_watches = await scraper.scrape()
            
            # Send notifications
            notifications_sent = 0
            if new_watches and APP_CONFIG.enable_notifications:
                site_config = SITE_CONFIGS[site_key]
                notifications_sent = await self.notification_manager.send_notifications(
                    new_watches,
                    site_config
                )
            
            # Update session statistics
            total_found = len(scraper.seen_ids) - len(self.seen_items.get(site_key, set()))
            session.add_site_result(
                site_key,
                total_found=total_found,
                new_found=len(new_watches),
                notifications=notifications_sent
            )
            
            # Update global seen items
            self.seen_items[site_key] = scraper.seen_ids
            
            # Save seen items after each site
            self.persistence.save_seen_items(self.seen_items)
            
        except Exception as e:
            self.logger.exception(f"Error scraping {site_key}: {e}")
            session.add_site_result(site_key, 0, 0, 0, errors=1)
    
    async def run_continuous(self):
        """Run continuous monitoring with configured interval."""
        self.running = True
        self.logger.info(
            f"Starting continuous monitoring with {APP_CONFIG.check_interval_seconds}s interval"
        )
        
        while self.running:
            try:
                # Run monitoring cycle
                await self.run_monitoring_cycle()
                
                # Wait for next cycle or shutdown
                try:
                    await asyncio.wait_for(
                        self.shutdown_event.wait(),
                        timeout=APP_CONFIG.check_interval_seconds
                    )
                    # If we get here, shutdown was requested
                    break
                except asyncio.TimeoutError:
                    # Normal timeout, continue to next cycle
                    pass
                    
            except Exception as e:
                self.logger.exception(f"Error in monitoring cycle: {e}")
                # Wait a bit before retrying
                await asyncio.sleep(10)
        
        self.logger.info("Continuous monitoring stopped")
    
    async def validate_configuration(self) -> bool:
        """
        Validate the configuration and test connections.
        
        Returns:
            True if all validations pass
        """
        all_valid = True
        
        self.logger.info("Validating configuration...")
        
        # Check scrapers
        for site_key, site_config in SITE_CONFIGS.items():
            if site_key not in SCRAPER_CLASSES:
                self.logger.warning(f"No scraper implementation for {site_key}")
                all_valid = False
        
        # Check webhooks
        for site_key, site_config in SITE_CONFIGS.items():
            webhook_url = site_config.webhook_url
            if not webhook_url:
                self.logger.warning(
                    f"No webhook configured for {site_key}. "
                    f"Set environment variable: {site_config.webhook_env_var}"
                )
            else:
                # Test webhook
                self.logger.info(f"Testing webhook for {site_key}...")
                success = await self.notification_manager.test_webhook(webhook_url)
                if success:
                    self.logger.info(f"✓ Webhook test successful for {site_key}")
                else:
                    self.logger.error(f"✗ Webhook test failed for {site_key}")
                    all_valid = False
        
        return all_valid
    
    def get_statistics(self, days: int = 7) -> Dict:
        """Get monitoring statistics."""
        return self.persistence.get_session_statistics(days)