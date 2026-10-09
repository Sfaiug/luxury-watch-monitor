"""Main monitor orchestrator for watch monitor application."""

import asyncio
import signal
import os
from typing import Dict, Set, Optional, Type
import aiohttp

from config import APP_CONFIG, SITE_CONFIGS
from models import ScrapingSession
from persistence import PersistenceManager, SeenIds
from notifications import NotificationManager
from logging_config import setup_logging, PerformanceLogger
from scrapers.base import BaseScraper
from memory_monitor import MemoryMonitor
from utils import clear_exchange_rate_cache
from action_store import ActionStore
from discord_interactions import DiscordInteractionServer, discord_route_enabled
from muv_service import MUVActionService
from filters import Filter, FilterStore
from filter_flow import DiscordApi, FilterFlow

# Import all scraper implementations
from scrapers.worldoftime import WorldOfTimeScraper
from scrapers.grimmeissen import GrimmeissenScraper
from scrapers.tropicalwatch import TropicalWatchScraper
from scrapers.juwelier_exchange import JuwelierExchangeScraper
from scrapers.watch_out import WatchOutScraper
from scrapers.rueschenbeck import RueschenbeckScraper
from scrapers.bachmann_scher import BachmannScherScraper

# Map site keys to scraper classes
SCRAPER_CLASSES: Dict[str, Type[BaseScraper]] = {
    "worldoftime": WorldOfTimeScraper,
    "grimmeissen": GrimmeissenScraper,
    "tropicalwatch": TropicalWatchScraper,
    "juwelier_exchange": JuwelierExchangeScraper,
    "watch_out": WatchOutScraper,
    "rueschenbeck": RueschenbeckScraper,
    "bachmann_scher": BachmannScherScraper,
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
        self.action_store: Optional[ActionStore] = None
        self.muv_service: Optional[MUVActionService] = None
        self.discord_interaction_server: Optional[DiscordInteractionServer] = None
        self.memory_monitor = MemoryMonitor()
        self._last_muv_offer_link_check = 0.0

        # State
        self.seen_items: Dict[str, Set[str]] = {}
        self.scrapers: Dict[str, BaseScraper] = {}
        self.filter_store = FilterStore(APP_CONFIG.filters_file)
        self.filter_keys: Set[str] = set()
        self.filter_flow: Optional[FilterFlow] = None
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
            enable_cleanup_closed=True,  # Clean up closed connections
        )

        timeout = aiohttp.ClientTimeout(
            total=APP_CONFIG.request_timeout,
            connect=10,  # Connection timeout
            sock_read=APP_CONFIG.request_timeout,
        )

        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={"User-Agent": APP_CONFIG.user_agent},
        )

        # Initialize optional MUV action services
        muv_features_enabled = (
            APP_CONFIG.enable_muv_actions
            or APP_CONFIG.discord_interactions_enabled
            or APP_CONFIG.muv_http_actions_enabled
            or bool(APP_CONFIG.muv_offer_link_urls)
        )
        if muv_features_enabled:
            self.action_store = ActionStore(APP_CONFIG.action_store_file)
            self.muv_service = MUVActionService(
                self.session, self.action_store, self.logger
            )
            await self.muv_service.register_configured_offer_links()

        # Initialize notification manager
        self.notification_manager = NotificationManager(
            self.session, self.logger, self.action_store
        )

        if (
            APP_CONFIG.discord_interactions_enabled
            or APP_CONFIG.muv_http_actions_enabled
        ):
            if not self.action_store or not self.muv_service:
                raise RuntimeError("MUV action store failed to initialize")
            # The "New filter" button needs its presses answered, the bot to
            # make channels, and a channel of the shops' to stand beside
            shops_channel = next(
                filter(None, map(self.notification_manager.bot_channel_id, SITE_CONFIGS.values())),
                None,
            )
            if discord_route_enabled() and APP_CONFIG.discord_bot_token and shops_channel:
                self.filter_flow = FilterFlow(
                    self.filter_store,
                    DiscordApi(
                        self.session,
                        APP_CONFIG.discord_bot_token,
                        APP_CONFIG.discord_api_base_url,
                    ),
                    self.logger,
                    self._scan_new_filter,
                    shops_channel,
                )
            self.discord_interaction_server = DiscordInteractionServer(
                self.action_store,
                self.muv_service,
                self.logger,
                self.filter_flow,
            )
            await self.discord_interaction_server.start()

        # Load seen items
        self.seen_items = self.persistence.load_seen_items()

        # Initialize scrapers
        for site_key, site_config in SITE_CONFIGS.items():
            scraper_class = SCRAPER_CLASSES.get(site_key)
            if scraper_class:
                scraper = scraper_class(site_config, self.session, self.logger)

                # Set seen IDs for the scraper
                site_seen_ids = self.seen_items.setdefault(site_key, SeenIds())
                scraper.set_seen_ids(site_seen_ids)

                self.scrapers[site_key] = scraper
            else:
                self.logger.warning(f"No scraper implementation found for {site_key}")

        self.logger.info("Watch monitor initialized successfully")

    async def cleanup(self):
        """Clean up resources with explicit resource management."""
        self.logger.info("Starting cleanup process...")

        try:
            if self.discord_interaction_server:
                try:
                    self.logger.debug("Stopping Discord interaction server...")
                    await self.discord_interaction_server.stop()
                    self.discord_interaction_server = None
                except Exception as e:
                    self.logger.error(
                        f"Error stopping Discord interaction server: {e}", exc_info=True
                    )

            # Close aiohttp session with proper error handling
            if self.session:
                try:
                    self.logger.debug("Closing aiohttp session...")

                    # ENHANCED: Close the session properly
                    if not self.session.closed:
                        await self.session.close()

                    # INCREASED DELAY: Give more time for connections to close
                    await asyncio.sleep(0.5)  # Increased from 0.25

                    # ENHANCED: Force connector cleanup
                    if hasattr(self.session, "_connector") and self.session._connector:
                        if not self.session._connector.closed:
                            await self.session._connector.close()

                    self.session = None
                    self.logger.debug("aiohttp session closed successfully")
                except Exception as e:
                    self.logger.error(
                        f"Error closing aiohttp session: {e}", exc_info=True
                    )

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
                self.muv_service = None

                if self.action_store:
                    self.action_store.close()
                    self.action_store = None

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

            # ENHANCED: Clear scraper internal state
            self.logger.debug("Clearing scraper internal state...")
            for site_key, scraper in self.scrapers.items():
                # Reset any cached data in scrapers (if present)
                if hasattr(scraper, "_cache"):
                    scraper._cache = {}
                    self.logger.debug(f"Cleared cache for {site_key}")

            # Trim session history
            self.logger.debug("Trimming session history...")
            self.persistence.cleanup_old_data()

            # Save seen items, each shop's trimmed to its limit
            self.logger.debug("Trimming seen items...")
            self.persistence.save_seen_items(self.seen_items)

            # Force garbage collection
            self.logger.debug("Forcing garbage collection...")
            collected = self.memory_monitor.force_garbage_collection()
            self.logger.info(
                f"Garbage collection complete: "
                f"gen0={collected[0]}, gen1={collected[1]}, gen2={collected[2]} objects collected"
            )

            # Force memory return to OS using malloc_trim
            self.logger.debug("Forcing memory return to OS...")
            trim_success = self.memory_monitor.trim_memory()
            if trim_success:
                self.logger.info("Successfully trimmed memory and returned to OS")
            else:
                self.logger.debug("malloc_trim not available (using GC only)")

            # Log memory after trim
            memory_after_trim = self.memory_monitor.get_current_usage_mb()
            trim_freed = memory_before - memory_after_trim
            if trim_freed > 0:
                self.logger.info(f"Memory freed by malloc_trim: {trim_freed:.2f}MB")

            # Log memory after cleanup
            memory_after = memory_after_trim
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
                with open(
                    self.persistence.session_history_file, "w", encoding="utf-8"
                ) as f:
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
            self.persistence.trim_seen_items(self.seen_items, emergency_seen_limit)

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

            # CRITICAL: Force aggressive memory return to OS
            self.logger.critical("Forcing aggressive memory return to OS...")
            trim_success = self.memory_monitor.trim_memory()
            if trim_success:
                self.logger.warning(
                    "Successfully forced memory trim in emergency cleanup"
                )

                # Log memory after emergency trim
                memory_after_trim = self.memory_monitor.get_current_usage_mb()
                emergency_trim_freed = memory_before - memory_after_trim
                if emergency_trim_freed > 0:
                    self.logger.warning(
                        f"Emergency malloc_trim freed {emergency_trim_freed:.2f}MB "
                        f"(total freed in emergency: {memory_before - memory_after_trim:.2f}MB)"
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
        if self.filter_flow:
            await self.filter_flow.tend()
        self._sync_filters()

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
                skip_sites = (
                    os.environ.get("SKIP_SITES", "").split(",")
                    if os.environ.get("SKIP_SITES")
                    else []
                )
                if site_key in skip_sites:
                    self.logger.info(f"Skipping {site_key} (in SKIP_SITES)")
                    continue

                task = scrape_site_with_semaphore(site_key, scraper)
                tasks.append(task)

            # Wait for all to complete
            await asyncio.gather(*tasks)

            # Poll reviewed MUV offer links without a separate worker process.
            await self._monitor_muv_offer_links()

            # Finalize session
            session.finalize()

            # Log memory usage at end of cycle
            memory_end = self.memory_monitor.get_current_usage_mb()
            session.memory_usage_end_mb = memory_end
            session.memory_delta_mb = memory_end - memory_start
            self.memory_monitor.log_memory_stats(self.logger, "cycle end")

            # Check memory thresholds and log warnings
            self.memory_monitor.check_memory_threshold(
                self.logger, APP_CONFIG.memory_warning_threshold_mb, "warning threshold"
            )

            # Check critical threshold and trigger emergency cleanup if exceeded
            if self.memory_monitor.check_memory_threshold(
                self.logger,
                APP_CONFIG.memory_critical_threshold_mb,
                "critical threshold",
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

    def _sync_filters(self):
        """One scraper per filter: new filters get theirs, a removed one loses it."""
        try:
            filters = {f.key: f for f in self.filter_store.all()}
        except Exception as e:
            # The shops are scanned all the same, and the filters as last read
            self.logger.error(f"Filters could not be read: {e}")
            return

        for key in self.filter_keys - set(filters):
            self.scrapers.pop(key, None)
            self.seen_items.pop(key, None)
        for key in set(filters) - self.filter_keys:
            try:
                scraper = filters[key].scraper(self.session, self.logger)
            except Exception as e:
                # A marketplace or seller this version does not know. Said once:
                # the filter counts as known and waits in the file
                self.logger.error(f"Filter {key} cannot be searched: {e!r}")
                continue
            scraper.set_seen_ids(self.seen_items.setdefault(key, SeenIds()))
            self.scrapers[key] = scraper
        self.filter_keys = set(filters)

    async def _scan_new_filter(self, new: Filter):
        """A filter just made is scanned at once, not at the next cycle."""
        self._sync_filters()
        if new.key in self.scrapers:
            await self._scrape_single_site(new.key, self.scrapers[new.key], ScrapingSession())

    async def _scrape_single_site(
        self, site_key: str, scraper: BaseScraper, session: ScrapingSession
    ):
        """Scrape a single site and update session."""
        try:
            self.logger.info(f"Starting scrape for {site_key}")

            # Scrape the site
            new_watches = await scraper.scrape()

            # Enhanced logging for debugging
            if new_watches:
                self.logger.info(
                    f"[{site_key}] Found {len(new_watches)} NEW watches to notify about:"
                )
                for watch in new_watches[:3]:  # Log first 3 for debugging
                    self.logger.debug(
                        f"  - {watch.title} (ID: {watch.composite_id[:8]}...)"
                    )

            # Send notifications
            notifications_sent = 0
            if new_watches and APP_CONFIG.enable_notifications:
                self.logger.info(
                    f"[{site_key}] Sending {len(new_watches)} notifications..."
                )
                notifications_sent = await self.notification_manager.send_notifications(
                    new_watches, scraper.config
                )
                if notifications_sent < len(new_watches):
                    self.logger.warning(
                        f"[{site_key}] Only {notifications_sent}/{len(new_watches)} notifications sent successfully"
                    )
            elif new_watches and not APP_CONFIG.enable_notifications:
                self.logger.info(
                    f"[{site_key}] Notifications disabled - would have sent {len(new_watches)}"
                )

            # Update session statistics
            total_found = len(scraper.seen_ids) - len(
                self.seen_items.get(site_key, set())
            )
            self.logger.debug(
                f"[{site_key}] Stats - Total seen: {len(scraper.seen_ids)}, "
                f"Previously seen: {len(self.seen_items.get(site_key, set()))}, "
                f"New: {len(new_watches)}"
            )
            session.add_site_result(
                site_key,
                total_found=total_found,
                new_found=len(new_watches),
                notifications=notifications_sent,
            )

            # Update global seen items
            self.seen_items[site_key] = scraper.seen_ids

            # Save seen items after each site
            self.persistence.save_seen_items(self.seen_items)

        except Exception as e:
            self.logger.exception(f"Error scraping {site_key}: {e}")
            session.add_site_result(site_key, 0, 0, 0, errors=1)

    async def _monitor_muv_offer_links(self, *, force: bool = False) -> int:
        """Poll stored MUV offer links and post changed states to Discord."""
        if not self.muv_service:
            return 0

        interval = max(APP_CONFIG.muv_offer_link_poll_seconds, 0)
        now = asyncio.get_running_loop().time()
        if (
            not force
            and self._last_muv_offer_link_check
            and now - self._last_muv_offer_link_check < interval
        ):
            return 0

        self._last_muv_offer_link_check = now
        try:
            sent = await self.muv_service.monitor_offer_links()
            if sent:
                self.logger.info("Sent %s MUV offer link update(s)", sent)
            return sent
        except Exception as exc:
            self.logger.exception("Error monitoring MUV offer links: %s", exc)
            return 0

    async def run_continuous(self) -> bool:
        """
        Run continuous monitoring with configured interval.

        Returns:
            bool: True if restart is requested, False otherwise
        """
        self.running = True
        self.logger.info(
            f"Starting continuous monitoring with {APP_CONFIG.check_interval_seconds}s interval"
        )

        should_restart = False

        while self.running:
            try:
                # Increment cycle counter
                self.cycle_count += 1

                # Run monitoring cycle
                await self.run_monitoring_cycle()

                # Perform periodic cleanup every N cycles
                if self.cycle_count % APP_CONFIG.force_gc_every_n_cycles == 0:
                    self._perform_periodic_cleanup()

                # Suggest restart after 100 cycles (~8 hours) for complete memory reclamation
                max_cycles = int(os.getenv("MAX_CYCLES_BEFORE_RESTART", "100"))
                if max_cycles > 0 and self.cycle_count >= max_cycles:
                    self.logger.warning(
                        f"Reached maximum cycle count ({max_cycles}). "
                        f"Requesting process restart for complete memory reclamation."
                    )
                    self.running = False
                    should_restart = True
                    break

                # Wait for next cycle or shutdown
                try:
                    await asyncio.wait_for(
                        self.shutdown_event.wait(),
                        timeout=APP_CONFIG.check_interval_seconds,
                    )
                    # If we get here, shutdown was requested
                    self.running = False
                    break
                except asyncio.TimeoutError:
                    # Normal timeout, continue to next cycle
                    pass

            except Exception as e:
                self.logger.exception(f"Error in monitoring cycle: {e}")
                # Wait a bit before retrying
                await asyncio.sleep(10)

        self.logger.info(f"Continuous monitoring stopped (restart={should_restart})")
        return should_restart

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
