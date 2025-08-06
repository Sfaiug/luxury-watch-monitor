"""Tests for watch monitor orchestrator."""

import pytest
import asyncio
import signal
from unittest.mock import AsyncMock, Mock, patch, MagicMock
from datetime import datetime

from monitor import WatchMonitor, SCRAPER_CLASSES
from models import WatchData, ScrapingSession
from config import SITE_CONFIGS


class TestWatchMonitor:
    """Test WatchMonitor orchestrator functionality."""
    
    def test_watch_monitor_initialization(self):
        """Test WatchMonitor initialization."""
        monitor = WatchMonitor(log_level="DEBUG", log_file="/tmp/test.log")
        
        assert monitor.logger is not None
        assert monitor.persistence is not None
        assert monitor.session is None  # Not initialized yet
        assert monitor.notification_manager is None  # Not initialized yet
        assert monitor.seen_items == {}
        assert monitor.scrapers == {}
        assert monitor.running is False
    
    @pytest.mark.asyncio
    async def test_initialize_success(self, temp_dir):
        """Test successful monitor initialization."""
        with patch('monitor.aiohttp.ClientSession') as mock_session_class:
            with patch('monitor.NotificationManager') as mock_notification_class:
                with patch('monitor.PersistenceManager') as mock_persistence_class:
                    with patch('monitor.SITE_CONFIGS', {"test_site": Mock()}):
                        with patch('monitor.SCRAPER_CLASSES', {"test_site": Mock()}):
                            
                            mock_session = AsyncMock()
                            mock_session_class.return_value = mock_session
                            
                            mock_persistence = Mock()
                            mock_persistence.load_seen_items.return_value = {"test_site": {"id1", "id2"}}
                            mock_persistence_class.return_value = mock_persistence
                            
                            mock_scraper_class = Mock()
                            mock_scraper = Mock()
                            mock_scraper_class.return_value = mock_scraper
                            
                            monitor = WatchMonitor()
                            await monitor.initialize()
                            
                            assert monitor.session == mock_session
                            assert monitor.notification_manager is not None
                            assert "test_site" in monitor.seen_items
                            assert len(monitor.scrapers) > 0 or len(SCRAPER_CLASSES) == 0
    
    @pytest.mark.asyncio
    async def test_cleanup(self):
        """Test monitor cleanup."""
        monitor = WatchMonitor()
        monitor.session = AsyncMock()
        monitor.persistence = Mock()
        monitor.seen_items = {"site1": {"id1", "id2"}}
        
        await monitor.cleanup()
        
        monitor.session.close.assert_called_once()
        monitor.persistence.save_seen_items.assert_called_once_with(monitor.seen_items)
    
    def test_handle_shutdown(self):
        """Test shutdown signal handling."""
        monitor = WatchMonitor()
        monitor.running = True
        
        # Simulate signal handler
        monitor._handle_shutdown(signal.SIGINT, None)
        
        assert monitor.running is False
        assert monitor.shutdown_event.is_set()
    
    @pytest.mark.asyncio
    async def test_run_monitoring_cycle_success(self):
        """Test successful monitoring cycle."""
        monitor = WatchMonitor()
        
        # Mock scrapers
        mock_scraper1 = AsyncMock()
        mock_scraper1.scrape.return_value = [
            WatchData(title="Watch 1", url="https://example.com/1", site_name="Site 1", site_key="site1"),
            WatchData(title="Watch 2", url="https://example.com/2", site_name="Site 1", site_key="site1")
        ]
        mock_scraper1.seen_ids = {"id1", "id2", "id3"}
        
        mock_scraper2 = AsyncMock()
        mock_scraper2.scrape.return_value = [
            WatchData(title="Watch 3", url="https://example.com/3", site_name="Site 2", site_key="site2")
        ]
        mock_scraper2.seen_ids = {"id4"}
        
        monitor.scrapers = {
            "site1": mock_scraper1,
            "site2": mock_scraper2
        }
        
        # Mock seen items
        monitor.seen_items = {
            "site1": {"old_id1"},
            "site2": set()
        }
        
        # Mock notification manager
        monitor.notification_manager = AsyncMock()
        monitor.notification_manager.send_notifications.return_value = 2
        
        # Mock persistence
        monitor.persistence = Mock()
        
        with patch('monitor.SITE_CONFIGS', {
            "site1": Mock(name="Site 1"),
            "site2": Mock(name="Site 2")
        }):
            with patch('monitor.APP_CONFIG') as mock_config:
                mock_config.enable_notifications = True
                mock_config.max_concurrent_scrapers = 2
                
                session = await monitor.run_monitoring_cycle()
        
        assert isinstance(session, ScrapingSession)
        assert session.sites_scraped == 2
        assert session.total_new_watches == 3  # 2 + 1
        assert session.ended_at is not None
        
        # Verify scrapers were called
        mock_scraper1.scrape.assert_called_once()
        mock_scraper2.scrape.assert_called_once()
        
        # Verify notifications were sent
        assert monitor.notification_manager.send_notifications.call_count == 2
        
        # Verify persistence was called
        monitor.persistence.save_session.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_run_monitoring_cycle_with_errors(self):
        """Test monitoring cycle with scraper errors."""
        monitor = WatchMonitor()
        
        # Mock scrapers - one succeeds, one fails
        mock_scraper1 = AsyncMock()
        mock_scraper1.scrape.return_value = [
            WatchData(title="Watch 1", url="https://example.com/1", site_name="Site 1", site_key="site1")
        ]
        mock_scraper1.seen_ids = {"id1"}
        
        mock_scraper2 = AsyncMock()
        mock_scraper2.scrape.side_effect = Exception("Scraping error")
        mock_scraper2.seen_ids = set()
        
        monitor.scrapers = {
            "site1": mock_scraper1,
            "site2": mock_scraper2
        }
        
        monitor.seen_items = {"site1": set(), "site2": set()}
        monitor.notification_manager = AsyncMock()
        monitor.persistence = Mock()
        
        with patch('monitor.SITE_CONFIGS', {
            "site1": Mock(name="Site 1"),
            "site2": Mock(name="Site 2")
        }):
            with patch('monitor.APP_CONFIG') as mock_config:
                mock_config.max_concurrent_scrapers = 2
                
                session = await monitor.run_monitoring_cycle()
        
        assert session.sites_scraped == 2
        assert session.errors_encountered == 1  # One scraper failed
        assert session.total_new_watches == 1   # Only successful scraper
    
    @pytest.mark.asyncio
    async def test_run_monitoring_cycle_notifications_disabled(self):
        """Test monitoring cycle with notifications disabled."""
        monitor = WatchMonitor()
        
        mock_scraper = AsyncMock()
        mock_scraper.scrape.return_value = [
            WatchData(title="Watch 1", url="https://example.com/1", site_name="Site 1", site_key="site1")
        ]
        mock_scraper.seen_ids = {"id1"}
        
        monitor.scrapers = {"site1": mock_scraper}
        monitor.seen_items = {"site1": set()}
        monitor.notification_manager = AsyncMock()
        monitor.persistence = Mock()
        
        with patch('monitor.SITE_CONFIGS', {"site1": Mock(name="Site 1")}):
            with patch('monitor.APP_CONFIG') as mock_config:
                mock_config.enable_notifications = False
                mock_config.max_concurrent_scrapers = 1
                
                session = await monitor.run_monitoring_cycle()
        
        assert session.notifications_sent == 0
        monitor.notification_manager.send_notifications.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_scrape_single_site_success(self):
        """Test scraping a single site successfully."""
        monitor = WatchMonitor()
        
        mock_scraper = AsyncMock()
        new_watches = [
            WatchData(title="New Watch", url="https://example.com/new", site_name="Site 1", site_key="site1")
        ]
        mock_scraper.scrape.return_value = new_watches
        mock_scraper.seen_ids = {"id1", "id2", "id3"}  # 3 total IDs
        
        session = ScrapingSession(session_id="test")
        monitor.seen_items = {"site1": {"id1"}}  # 1 previously seen
        monitor.notification_manager = AsyncMock()
        monitor.notification_manager.send_notifications.return_value = 1
        monitor.persistence = Mock()
        
        with patch('monitor.SITE_CONFIGS', {"site1": Mock(name="Site 1")}):
            with patch('monitor.APP_CONFIG') as mock_config:
                mock_config.enable_notifications = True
                
                await monitor._scrape_single_site("site1", mock_scraper, session)
        
        # Check session was updated correctly
        assert "site1" in session.site_stats
        assert session.site_stats["site1"]["new_found"] == 1
        assert session.site_stats["site1"]["notifications_sent"] == 1
        assert session.site_stats["site1"]["errors"] == 0
        
        # Check seen items were updated
        assert monitor.seen_items["site1"] == {"id1", "id2", "id3"}
        
        # Verify persistence was called
        monitor.persistence.save_seen_items.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_scrape_single_site_error(self):
        """Test scraping a single site with error."""
        monitor = WatchMonitor()
        
        mock_scraper = AsyncMock()
        mock_scraper.scrape.side_effect = Exception("Scraping failed")
        
        session = ScrapingSession(session_id="test")
        monitor.seen_items = {}
        
        await monitor._scrape_single_site("site1", mock_scraper, session)
        
        # Should have recorded the error
        assert "site1" in session.site_stats
        assert session.site_stats["site1"]["errors"] == 1
        assert session.site_stats["site1"]["new_found"] == 0
    
    @pytest.mark.asyncio
    async def test_run_continuous_normal_cycle(self):
        """Test continuous monitoring with normal cycle."""
        monitor = WatchMonitor()
        monitor.run_monitoring_cycle = AsyncMock()
        
        # Mock the monitoring cycle to run once then stop
        async def mock_cycle():
            monitor.running = False  # Stop after first cycle
            return ScrapingSession(session_id="test")
        
        monitor.run_monitoring_cycle.side_effect = mock_cycle
        
        with patch('monitor.APP_CONFIG') as mock_config:
            mock_config.check_interval_seconds = 0.01  # Very short interval
            
            await monitor.run_continuous()
        
        # Should have run at least one cycle
        monitor.run_monitoring_cycle.assert_called()
        assert monitor.running is False
    
    @pytest.mark.asyncio
    async def test_run_continuous_with_shutdown(self):
        """Test continuous monitoring with shutdown signal."""
        monitor = WatchMonitor()
        monitor.run_monitoring_cycle = AsyncMock(return_value=ScrapingSession(session_id="test"))
        
        # Simulate shutdown signal after short delay
        async def trigger_shutdown():
            await asyncio.sleep(0.01)
            monitor.shutdown_event.set()
        
        with patch('monitor.APP_CONFIG') as mock_config:
            mock_config.check_interval_seconds = 1  # Long interval
            
            # Run both continuous monitoring and shutdown trigger
            await asyncio.gather(
                monitor.run_continuous(),
                trigger_shutdown()
            )
        
        assert monitor.running is False
    
    @pytest.mark.asyncio
    async def test_run_continuous_with_error(self):
        """Test continuous monitoring with monitoring cycle error."""
        monitor = WatchMonitor()
        
        call_count = 0
        async def mock_cycle():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Monitoring error")
            else:
                monitor.running = False  # Stop after error handling
                return ScrapingSession(session_id="test")
        
        monitor.run_monitoring_cycle = AsyncMock(side_effect=mock_cycle)
        
        with patch('monitor.APP_CONFIG') as mock_config:
            mock_config.check_interval_seconds = 0.01
            
            with patch('asyncio.sleep'):  # Mock sleep for error recovery
                await monitor.run_continuous()
        
        # Should continue after error
        assert monitor.run_monitoring_cycle.call_count >= 2
    
    @pytest.mark.asyncio
    async def test_validate_configuration_success(self):
        """Test configuration validation with valid setup."""
        monitor = WatchMonitor()
        monitor.notification_manager = AsyncMock()
        monitor.notification_manager.test_webhook.return_value = True
        
        with patch('monitor.SITE_CONFIGS', {
            "site1": Mock(webhook_url="https://discord.com/webhooks/test1"),
            "site2": Mock(webhook_url="https://discord.com/webhooks/test2")
        }):
            with patch('monitor.SCRAPER_CLASSES', {
                "site1": Mock(),
                "site2": Mock()
            }):
                result = await monitor.validate_configuration()
        
        assert result is True
        assert monitor.notification_manager.test_webhook.call_count == 2
    
    @pytest.mark.asyncio
    async def test_validate_configuration_missing_scraper(self):
        """Test configuration validation with missing scraper."""
        monitor = WatchMonitor()
        monitor.notification_manager = AsyncMock()
        
        with patch('monitor.SITE_CONFIGS', {
            "site1": Mock(webhook_url="https://discord.com/webhooks/test1"),
            "missing_scraper": Mock(webhook_url="https://discord.com/webhooks/test2")
        }):
            with patch('monitor.SCRAPER_CLASSES', {
                "site1": Mock()
                # "missing_scraper" not in SCRAPER_CLASSES
            }):
                result = await monitor.validate_configuration()
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_validate_configuration_missing_webhook(self):
        """Test configuration validation with missing webhook."""
        monitor = WatchMonitor()
        monitor.notification_manager = AsyncMock()
        
        with patch('monitor.SITE_CONFIGS', {
            "site1": Mock(webhook_url="https://discord.com/webhooks/test1"),
            "site2": Mock(webhook_url=None)  # Missing webhook
        }):
            with patch('monitor.SCRAPER_CLASSES', {
                "site1": Mock(),
                "site2": Mock()
            }):
                result = await monitor.validate_configuration()
        
        # Should still return True but log warning
        assert result is True
        monitor.notification_manager.test_webhook.assert_called_once()  # Only for site1
    
    @pytest.mark.asyncio
    async def test_validate_configuration_webhook_test_failure(self):
        """Test configuration validation with webhook test failure."""
        monitor = WatchMonitor()
        monitor.notification_manager = AsyncMock()
        monitor.notification_manager.test_webhook.return_value = False
        
        with patch('monitor.SITE_CONFIGS', {
            "site1": Mock(webhook_url="https://discord.com/webhooks/invalid")
        }):
            with patch('monitor.SCRAPER_CLASSES', {
                "site1": Mock()
            }):
                result = await monitor.validate_configuration()
        
        assert result is False
    
    def test_get_statistics(self):
        """Test getting monitoring statistics."""
        monitor = WatchMonitor()
        monitor.persistence = Mock()
        
        expected_stats = {
            "total_sessions": 10,
            "total_new_watches": 50,
            "success_rate": 90.0
        }
        monitor.persistence.get_session_statistics.return_value = expected_stats
        
        result = monitor.get_statistics(days=7)
        
        assert result == expected_stats
        monitor.persistence.get_session_statistics.assert_called_once_with(7)
    
    @pytest.mark.asyncio
    async def test_integration_full_monitoring_cycle(self):
        """Integration test for a complete monitoring cycle."""
        # This test simulates a more realistic monitoring scenario
        monitor = WatchMonitor()
        
        # Set up mock components
        monitor.session = AsyncMock()
        monitor.notification_manager = AsyncMock()
        monitor.notification_manager.send_notifications.return_value = 1
        monitor.persistence = Mock()
        
        # Create mock scraper that returns new watches
        mock_scraper = AsyncMock()
        new_watch = WatchData(
            title="Rolex Submariner",
            url="https://example.com/rolex-submariner",
            site_name="Test Site",
            site_key="test_site",
            brand="Rolex",
            model="Submariner",
            price=Decimal("8500.00")
        )
        mock_scraper.scrape.return_value = [new_watch]
        mock_scraper.seen_ids = {new_watch.composite_id}
        
        monitor.scrapers = {"test_site": mock_scraper}
        monitor.seen_items = {"test_site": set()}  # No previously seen items
        
        with patch('monitor.SITE_CONFIGS', {
            "test_site": Mock(name="Test Site", webhook_url="https://discord.com/test")
        }):
            with patch('monitor.APP_CONFIG') as mock_config:
                mock_config.enable_notifications = True
                mock_config.max_concurrent_scrapers = 1
                
                session = await monitor.run_monitoring_cycle()
        
        # Verify the complete flow worked
        assert session.sites_scraped == 1
        assert session.total_new_watches == 1
        assert session.notifications_sent == 1
        assert session.errors_encountered == 0
        
        # Verify watch was added to seen items
        assert new_watch.composite_id in monitor.seen_items["test_site"]
        
        # Verify all components were called
        mock_scraper.scrape.assert_called_once()
        monitor.notification_manager.send_notifications.assert_called_once()
        monitor.persistence.save_session.assert_called_once()
        monitor.persistence.save_seen_items.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_concurrent_site_scraping(self):
        """Test concurrent scraping of multiple sites with semaphore control."""
        monitor = WatchMonitor()
        
        # Create multiple mock scrapers with different response times
        scrapers = {}
        for i in range(5):
            scraper = AsyncMock()
            
            async def mock_scrape(delay=i*0.01):
                await asyncio.sleep(delay)  # Simulate different response times
                return [WatchData(
                    title=f"Watch {i}",
                    url=f"https://example.com/watch{i}",
                    site_name=f"Site {i}",
                    site_key=f"site{i}"
                )]
            
            scraper.scrape = mock_scrape
            scraper.seen_ids = {f"id{i}"}
            scrapers[f"site{i}"] = scraper
        
        monitor.scrapers = scrapers
        monitor.seen_items = {f"site{i}": set() for i in range(5)}
        monitor.notification_manager = AsyncMock()
        monitor.persistence = Mock()
        
        site_configs = {f"site{i}": Mock(name=f"Site {i}") for i in range(5)}
        
        with patch('monitor.SITE_CONFIGS', site_configs):
            with patch('monitor.APP_CONFIG') as mock_config:
                mock_config.enable_notifications = False  # Disable for speed
                mock_config.max_concurrent_scrapers = 3  # Test semaphore limiting
                
                start_time = asyncio.get_event_loop().time()
                session = await monitor.run_monitoring_cycle()
                end_time = asyncio.get_event_loop().time()
        
        # All sites should have been scraped
        assert session.sites_scraped == 5
        assert session.total_new_watches == 5
        
        # With semaphore limiting, this should take longer than if all ran concurrently
        # but less than if they ran sequentially
        duration = end_time - start_time
        assert duration < 0.1  # Should still be reasonably fast
        
        # Verify all scrapers were called
        for scraper in scrapers.values():
            scraper.scrape.assert_called_once()