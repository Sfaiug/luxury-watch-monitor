"""Main monitor orchestrator for watch monitor application."""

import asyncio
import signal
import os
from typing import Dict, List, Set, Optional, Type
import aiohttp

from config import APP_CONFIG, SITE_CONFIGS, SiteConfig
from models import ScrapingSession, WatchData
from persistence import PersistenceManager
from notifications import NotificationManager
from logging_config import setup_logging, PerformanceLogger
from scrapers.base import BaseScraper
from memory_monitor import MemoryMonitor
from utils import clear_exchange_rate_cache

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
        self.memory_monitor = MemoryMonitor()
        
        # State
        self.seen_items: Dict[str, Set[str]] = {}
        self.scrapers: Dict[str, BaseScraper] = {}
        self.running = False
        self.shutdown_event = asyncio.Event()
        
        # Cycle tracking for periodic cleanup
        self.cycle_count = 0
        
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
        """Clean up resources with explicit resource management."""
        self.logger.info("Starting cleanup process...")
        
        try:
            # Close aiohttp session with proper error handling
            if self.session:
                try:
                    self.logger.debug("Closing aiohttp session...")
                    await self.session.close()
                    # Wait a bit for connections to close properly
                    await asyncio.sleep(0.25)
                    self.session = None
                    self.logger.debug("aiohttp session closed successfully")
                except Exception as e:
                    self.logger.error(f"Error closing aiohttp session: {e}", exc_info=True)
            
            # Save final state with error handling
            try:
                self.logger.debug("Saving seen items...")
                self.persistence.save_seen_items(self.seen_items)
                self.logger.debug("Seen items saved successfully")
            except Exception as e:
                self.logger.error(f"Error saving seen items: {e}", exc_info=True)
            
        finally:
            # Clear all references to allow garbage collection
            try:
                self.logger.debug("Clearing scrapers dictionary...")
                if self.scrapers:
                    self.scrapers.clear()
                    self.scrapers = {}

                self.logger.debug("Clearing seen_items dictionary...")
                if self.seen_items:
                    self.seen_items.clear()
                    self.seen_items = {}

                # Clear notification manager reference
                self.notification_manager = None

                # Clear module-level caches
                self.logger.debug("Clearing exchange rate cache...")
                clear_exchange_rate_cache()

                self.logger.info("Watch monitor cleaned up successfully")
            except Exception as e:
                self.logger.error(f"Error during final cleanup: {e}", exc_info=True)
    
    def _perform_periodic_cleanup(self):
        """
        Perform periodic cleanup to prevent memory leaks.
        
        This method is called every N cycles (configured by force_gc_every_n_cycles)
        to trim data structures and force garbage collection.
        """
        self.logger.info(f"Performing periodic cleanup (cycle {self.cycle_count})")
        
        try:
            # Log memory before cleanup
            memory_before = self.memory_monitor.get_current_usage_mb()
            self.logger.info(f"Memory before cleanup: {memory_before:.2f}MB")
            
            # Trim session history
            self.logger.debug("Trimming session history...")
            self.persistence.cleanup_old_data()
            
            # Trim seen items in memory
            self.logger.debug("Trimming seen items...")
            self.seen_items = self.persistence.trim_seen_items(self.seen_items)
            
            # Save trimmed seen items
            self.persistence.save_seen_items(self.seen_items)
            
            # Force garbage collection
            self.logger.debug("Forcing garbage collection...")
            collected = self.memory_monitor.force_garbage_collection()
            self.logger.info(
                f"Garbage collection complete: "
                f"gen0={collected[0]}, gen1={collected[1]}, gen2={collected[2]} objects collected"
            )
            
            # Log memory after cleanup
            memory_after = self.memory_monitor.get_current_usage_mb()
            memory_freed = memory_before - memory_after
            self.logger.info(
                f"Memory after cleanup: {memory_after:.2f}MB "
                f"(freed {memory_freed:.2f}MB)"
            )
            
        except Exception as e:
            self.logger.error(f"Error during periodic cleanup: {e}", exc_info=True)
    
    def _emergency_cleanup(self):
        """
        Perform emergency cleanup when memory exceeds critical threshold.
        
        This method is triggered when memory usage exceeds the critical threshold
        (default 500MB) and performs aggressive trimming of all data structures
        and multiple garbage collection passes to reclaim as much memory as possible.
        
        Requirements: 3.1, 4.1
        """
        self.logger.critical(
            "EMERGENCY CLEANUP TRIGGERED - Memory usage has exceeded critical threshold!"
        )
        
        try:
            # Log memory before emergency cleanup
            memory_before = self.memory_monitor.get_current_usage_mb()
            self.logger.critical(
                f"Memory before emergency cleanup: {memory_before:.2f}MB "
                f"(critical threshold: {APP_CONFIG.memory_critical_threshold_mb}MB)"
            )
            
            # Aggressive trimming of session history - reduce to 50% of normal limit
            emergency_session_limit = APP_CONFIG.max_session_history_entries // 2
            self.logger.warning(
                f"Aggressively trimming session history to {emergency_session_limit} entries..."
            )
            history = self.persistence.load_session_history()
            if len(history) > emergency_session_limit:
                trimmed_history = history[-emergency_session_limit:]
                with open(self.persistence.session_history_file, 'w', encoding='utf-8') as f:
                    import json
                    json.dump(trimmed_history, f, indent=2, ensure_ascii=False)
                self.logger.warning(
                    f"Emergency trimmed session history: {len(history)} -> {len(trimmed_history)} entries"
                )
            
            # Aggressive trimming of seen items - reduce to 50% of normal limit per site
            emergency_seen_limit = APP_CONFIG.max_seen_items_per_site // 2
            self.logger.warning(
                f"Aggressively trimming seen items to {emergency_seen_limit} per site..."
            )
            for site_key, items in self.seen_items.items():
                original_count = len(items)
                if original_count > emergency_seen_limit:
                    items_list = list(items)
                    trimmed_list = items_list[-emergency_seen_limit:]
                    self.seen_items[site_key] = set(trimmed_list)
                    self.logger.warning(
                        f"Emergency trimmed {site_key}: {original_count} -> {len(self.seen_items[site_key])} items"
                    )
            
            # Save aggressively trimmed seen items
            self.persistence.save_seen_items(self.seen_items)
            
            # Force multiple garbage collection passes (3 full passes)
            self.logger.warning("Forcing multiple garbage collection passes...")
            total_collected = [0, 0, 0]
            for pass_num in range(3):
                collected = self.memory_monitor.force_garbage_collection()
                total_collected = [total_collected[i] + collected[i] for i in range(3)]
                self.logger.warning(
                    f"GC pass {pass_num + 1}/3: "
                    f"gen0={collected[0]}, gen1={collected[1]}, gen2={collected[2]} objects collected"
                )
            
            self.logger.warning(
                f"Total garbage collection: "
                f"gen0={total_collected[0]}, gen1={total_collected[1]}, gen2={total_collected[2]} objects collected"
            )
            
            # Log memory after emergency cleanup
            memory_after = self.memory_monitor.get_current_usage_mb()
            memory_freed = memory_before - memory_after
            
            if memory_after > APP_CONFIG.memory_critical_threshold_mb:
                self.logger.critical(
                    f"Memory after emergency cleanup: {memory_after:.2f}MB "
                    f"(freed {memory_freed:.2f}MB) - STILL ABOVE CRITICAL THRESHOLD! "
                    f"Consider restarting the application or investigating for memory leaks."
                )
            else:
                self.logger.warning(
                    f"Memory after emergency cleanup: {memory_after:.2f}MB "
                    f"(freed {memory_freed:.2f}MB) - Successfully reduced below critical threshold."
                )
            
        except Exception as e:
            self.logger.critical(f"Error during emergency cleanup: {e}", exc_info=True)
    
    async def run_monitoring_cycle(self) -> ScrapingSession:
        """
        Run a single monitoring cycle across all sites.
        
        Returns:
            ScrapingSession with results
        """
        session = ScrapingSession()
        
        # Log memory usage at start of cycle
        memory_start = self.memory_monitor.get_current_usage_mb()
        session.memory_usage_start_mb = memory_start
        self.memory_monitor.log_memory_stats(self.logger, "cycle start")
        
        with PerformanceLogger(self.logger, "monitoring cycle"):
            # Scrape sites concurrently with semaphore control
            semaphore = asyncio.Semaphore(APP_CONFIG.max_concurrent_scrapers)
            
            async def scrape_site_with_semaphore(site_key: str, scraper: BaseScraper):
                async with semaphore:
                    return await self._scrape_single_site(site_key, scraper, session)
            
            # Create tasks for all sites
            tasks = []
            for site_key, scraper in self.scrapers.items():
                # Skip sites that consistently fail (can be configured)
                skip_sites = os.environ.get('SKIP_SITES', '').split(',') if os.environ.get('SKIP_SITES') else []
                if site_key in skip_sites:
                    self.logger.info(f"Skipping {site_key} (in SKIP_SITES)")
                    continue
                    
                task = scrape_site_with_semaphore(site_key, scraper)
                tasks.append(task)
            
            # Wait for all to complete
            await asyncio.gather(*tasks)
            
            # Finalize session
            session.finalize()
            
            # Log memory usage at end of cycle
            memory_end = self.memory_monitor.get_current_usage_mb()
            session.memory_usage_end_mb = memory_end
            session.memory_delta_mb = memory_end - memory_start
            self.memory_monitor.log_memory_stats(self.logger, "cycle end")
            
            # Check memory thresholds and log warnings
            self.memory_monitor.check_memory_threshold(
                self.logger,
                APP_CONFIG.memory_warning_threshold_mb,
                "warning threshold"
            )
            
            # Check critical threshold and trigger emergency cleanup if exceeded
            if self.memory_monitor.check_memory_threshold(
                self.logger,
                APP_CONFIG.memory_critical_threshold_mb,
                "critical threshold"
            ):
                self.logger.critical(
                    f"Memory usage is critically high! Triggering emergency cleanup..."
                )
                # Perform emergency cleanup immediately
                self._emergency_cleanup()
            
            # Save session history
            self.persistence.save_session(session)
            
            # Log summary
            self.logger.info(
                f"Monitoring cycle complete: "
                f"{session.total_new_watches} new watches found, "
                f"{session.notifications_sent} notifications sent, "
                f"memory delta: {session.memory_delta_mb:+.2f}MB"
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
            
            # Enhanced logging for debugging
            if new_watches:
                self.logger.info(f"[{site_key}] Found {len(new_watches)} NEW watches to notify about:")
                for watch in new_watches[:3]:  # Log first 3 for debugging
                    self.logger.debug(f"  - {watch.title} (ID: {watch.composite_id[:8]}...)")
            
            # Send notifications
            notifications_sent = 0
            if new_watches and APP_CONFIG.enable_notifications:
                site_config = SITE_CONFIGS[site_key]
                self.logger.info(f"[{site_key}] Sending {len(new_watches)} notifications...")
                notifications_sent = await self.notification_manager.send_notifications(
                    new_watches,
                    site_config
                )
                if notifications_sent < len(new_watches):
                    self.logger.warning(
                        f"[{site_key}] Only {notifications_sent}/{len(new_watches)} notifications sent successfully"
                    )
            elif new_watches and not APP_CONFIG.enable_notifications:
                self.logger.info(f"[{site_key}] Notifications disabled - would have sent {len(new_watches)}")
            
            # Update session statistics
            total_found = len(scraper.seen_ids) - len(self.seen_items.get(site_key, set()))
            self.logger.debug(
                f"[{site_key}] Stats - Total seen: {len(scraper.seen_ids)}, "
                f"Previously seen: {len(self.seen_items.get(site_key, set()))}, "
                f"New: {len(new_watches)}"
            )
            session.add_site_result(
                site_key,
                total_found=total_found,
                new_found=len(new_watches),
                notifications=notifications_sent
            )
            
            # Update global seen items
            self.seen_items[site_key] = scraper.seen_ids

            # Trim this site's items immediately to prevent accumulation
            if len(self.seen_items[site_key]) > APP_CONFIG.max_seen_items_per_site:
                items_list = list(self.seen_items[site_key])
                self.seen_items[site_key] = set(items_list[-APP_CONFIG.max_seen_items_per_site:])
                self.logger.debug(
                    f"[{site_key}] Trimmed seen items: {len(items_list)} -> {len(self.seen_items[site_key])}"
                )

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
                # Increment cycle counter
                self.cycle_count += 1
                
                # Run monitoring cycle
                await self.run_monitoring_cycle()
                
                # Perform periodic cleanup every N cycles
                if self.cycle_count % APP_CONFIG.force_gc_every_n_cycles == 0:
                    self._perform_periodic_cleanup()
                
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