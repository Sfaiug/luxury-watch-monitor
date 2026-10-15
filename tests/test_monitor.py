"""Tests for watch monitor orchestrator."""

import pytest
import asyncio
import signal
import json
import logging
import sqlite3
import csv
import os
from datetime import date, datetime, timedelta
from dataclasses import replace
from unittest.mock import AsyncMock, DEFAULT, Mock, patch
from decimal import Decimal

from config import APP_CONFIG, SITE_CONFIGS
from agent import Agent, Deals, Reading
from chrono24 import FULL_SET, USED
from filters import Filter, FilterStore
from monitor import WatchMonitor, SCRAPER_CLASSES
from models import WatchData, ScrapingSession
from notifications import NotificationManager
from negotiation import Negotiations, Negotiator
from persistence import SeenIds
from prices import Prices
from scrapers.base import BaseScraper
from worth import buy_limit
import controlling


def configure_monitor_config(
    mock_config,
    *,
    enable_notifications=True,
    max_concurrent_scrapers=2,
    check_interval_seconds=1,
):
    mock_config.enable_notifications = enable_notifications
    mock_config.max_concurrent_scrapers = max_concurrent_scrapers
    mock_config.check_interval_seconds = check_interval_seconds
    mock_config.max_seen_items_per_site = 1000
    mock_config.memory_warning_threshold_mb = 400
    mock_config.memory_critical_threshold_mb = 500
    mock_config.force_gc_every_n_cycles = 1000
    mock_config.enable_muv_actions = False
    mock_config.discord_interactions_enabled = False
    mock_config.muv_http_actions_enabled = False
    mock_config.muv_offer_link_urls = ""
    mock_config.muv_offer_link_poll_seconds = 900


@pytest.fixture
def controlling_monitor(tmp_path, monkeypatch):
    export = tmp_path / "controlling.csv"
    monkeypatch.setattr(APP_CONFIG, "controlling_file", str(export))
    monkeypatch.setattr(APP_CONFIG, "discord_bot_token", "bot-token")
    monkeypatch.setattr(APP_CONFIG, "discord_alert_channel_id", "42")
    monitor = WatchMonitor(log_level="ERROR")
    monitor.prices = Prices(tmp_path / "prices.sqlite3")
    monitor.logger = Mock()
    monitor.persistence = Mock()
    monitor.filter_store = Mock(all=Mock(return_value=[]))
    written = 0

    def write(problem="", **changes):
        nonlocal written
        values = {
            "Marke": "Rolex", "Referenznummer": "116610LN", "Box": "x", "Papiere": "x",
            "Ankaufdatum": date.today().strftime("%d.%m.%Y"), "EK": "8.000,00",
            "Verkaufsdatum": date.today().strftime("%d.%m.%Y"), "VK realisiert": "10.000,00",
            "Verkäufer": "Private Seller",
        }
        values.update(changes)
        with export.open("w", encoding="utf-8-sig", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=values.keys())
            writer.writeheader()
            writer.writerows([values] * 10)
        content = export.read_text(encoding="utf-8-sig")
        if problem == "renamed":
            export.write_text(content.replace(",EK,", ",Einkauf,"), encoding="utf-8-sig")
        elif problem == "semicolon":
            export.write_text(content.replace(",", ";"), encoding="utf-8-sig")
        elif problem == "encoding":
            export.write_bytes(content.encode("cp1252"))
        elif problem == "empty":
            export.write_text("", encoding="utf-8-sig")
        written += 1
        os.utime(export, (1_000_000_000 + written, 1_000_000_000 + written))

    write()
    yield monitor, write
    monitor.prices.close()


@pytest.mark.parametrize("problem,changes", [
    ("", {"Ankaufdatum": "2026-10-14", "Verkaufsdatum": "2026-10-14"}),
    ("", {"Ankaufdatum": "14.10.26", "Verkaufsdatum": "14.10.26"}),
    ("", {"EK": "1.000,-", "VK realisiert": "1.000,-"}),
    ("", {"EK": "30,000.00", "VK realisiert": "30,000.00"}),
    ("renamed", {}), ("semicolon", {}), ("encoding", {}), ("empty", {}),
])
async def test_unreadable_export_keeps_the_trades_and_buy_limit_and_warns_once(controlling_monitor, problem, changes):
    monitor, write = controlling_monitor
    await monitor._read_trades()
    before = buy_limit(monitor.prices, "116610LN", "used")
    assert before is not None
    # The baseline comes from the database, including after a restart.
    monitor.prices.close()
    monitor.prices = Prices(os.path.join(os.path.dirname(APP_CONFIG.controlling_file), "prices.sqlite3"))
    monitor._trades_read = None
    write(problem, **changes)

    with patch("monitor.controlling.read", wraps=controlling.read) as read, patch(
        "monitor.DiscordApi.call", new=AsyncMock(return_value=(201, {}))
    ) as posted:
        for _ in range(3):
            await monitor.run_monitoring_cycle()
        assert monitor.prices.trade_counts() == (10, 10)
        assert buy_limit(monitor.prices, "116610LN", "used") == before
        read.assert_called_once()
        posted.assert_awaited_once()
        method, path, message = posted.await_args.args
        assert (method, path) == ("POST", "/channels/42/messages")
        assert "previous trades are still in use" in message["content"]
        assert "Private Seller" not in message["content"]
        monitor.logger.error.assert_called_once()

        # Another unreadable file belongs to the same warning, until a good one arrives.
        write("semicolon")
        await monitor.run_monitoring_cycle()
        posted.assert_awaited_once()
        monitor.logger.error.assert_called_once()

        write(Referenznummer="126610LN")
        await monitor.run_monitoring_cycle()
        since = date.today() - timedelta(days=365)
        assert monitor.prices.traded_for("116610LN", False, since, True) == []
        assert monitor.prices.traded_for("126610LN", False, since, True) == [10000] * 10

        write("renamed")
        await monitor.run_monitoring_cycle()
        await monitor.run_monitoring_cycle()
        assert posted.await_count == 2
        assert monitor.logger.error.call_count == 2


@pytest.mark.parametrize("unavailable", ["failed_post", "no_channel", "no_token"])
async def test_unreadable_export_retries_the_warning_until_discord_accepts_it(controlling_monitor, monkeypatch, unavailable):
    monitor, write = controlling_monitor
    await monitor._read_trades()
    write("renamed")
    if unavailable == "no_channel":
        monkeypatch.setattr(APP_CONFIG, "discord_alert_channel_id", "")
        monkeypatch.setattr("monitor.SITE_CONFIGS", {})
    elif unavailable == "no_token":
        monkeypatch.setattr(APP_CONFIG, "discord_bot_token", "")

    replies = [(503, {}), (201, {})] if unavailable == "failed_post" else [(201, {})]
    with patch("monitor.DiscordApi.call", new=AsyncMock(side_effect=replies)) as posted:
        await monitor.run_monitoring_cycle()
        assert not monitor.prices.trades_warned
        monkeypatch.setattr(APP_CONFIG, "discord_alert_channel_id", "42")
        monkeypatch.setattr(APP_CONFIG, "discord_bot_token", "bot-token")
        await monitor.run_monitoring_cycle()
        await monitor.run_monitoring_cycle()
        assert monitor.prices.trades_warned
        assert posted.await_count == len(replies)
        monitor.logger.error.assert_called_once()


async def test_unreadable_export_can_warn_in_the_existing_shop_channel(controlling_monitor, monkeypatch):
    monitor, write = controlling_monitor
    monkeypatch.setattr(APP_CONFIG, "discord_alert_channel_id", "")
    monkeypatch.setenv("WORLDOFTIME_CHANNEL_ID", "42")
    write("renamed")

    with patch("monitor.DiscordApi.call", new=AsyncMock(return_value=(201, {}))) as posted:
        await monitor._read_trades()
    assert posted.await_args.args[1] == "/channels/42/messages"


@pytest.mark.parametrize("failure", ["read_error", "database_lock"])
async def test_unreadable_export_retries_transient_failures_without_another_upload(
    controlling_monitor, monkeypatch, tmp_path, failure
):
    monitor, write = controlling_monitor
    monkeypatch.setattr(APP_CONFIG, "discord_bot_token", "")
    monkeypatch.setattr("monitor.SITE_CONFIGS", {})
    await monitor._read_trades()
    write(Referenznummer="126610LN")
    modified = os.path.getmtime(APP_CONFIG.controlling_file)
    monitor.prices._db.execute("PRAGMA busy_timeout = 1")
    lock = sqlite3.connect(tmp_path / "prices.sqlite3")
    try:
        with patch("monitor.controlling.read", wraps=controlling.read) as read:
            if failure == "database_lock":
                lock.execute("BEGIN IMMEDIATE")
            else:
                read.side_effect = [PermissionError("Temporarily unavailable"), DEFAULT]
            await monitor._read_trades()
            assert monitor._trades_read != modified
            assert monitor.prices.traded_for("116610LN", False, date(2000, 1, 1), True) == [10000] * 10
            lock.rollback()

            await monitor._read_trades()
            await monitor._read_trades()
            assert os.path.getmtime(APP_CONFIG.controlling_file) == modified
            assert monitor._trades_read == modified
            assert monitor.prices.traded_for("126610LN", False, date(2000, 1, 1), True) == [10000] * 10
            assert monitor.prices.traded_for("116610LN", False, date(2000, 1, 1), True) == []
            assert read.call_count == 2
    finally:
        lock.close()


async def test_unreadable_export_warning_survives_restarts_until_readable_trades_arrive(controlling_monitor, tmp_path):
    monitor, write = controlling_monitor
    await monitor._read_trades()
    write("renamed")
    with patch("monitor.DiscordApi.call", new=AsyncMock(return_value=(201, {}))) as posted:
        await monitor._read_trades()
        posted.assert_awaited_once()
        monitor.prices.close()
        restarted = WatchMonitor(log_level="CRITICAL")
        restarted.prices = Prices(tmp_path / "prices.sqlite3")
        try:
            await restarted._read_trades()
            write("semicolon")
            await restarted._read_trades()
            posted.assert_awaited_once()
            assert restarted.prices.trades_warned

            write()
            await restarted._read_trades()
            assert not restarted.prices.trades_warned
            write("renamed")
            await restarted._read_trades()
            assert posted.await_count == 2
        finally:
            restarted.prices.close()


@pytest.mark.parametrize("first_status", [204, 503])
async def test_unreadable_export_warns_once_through_an_existing_webhook(
    controlling_monitor, monkeypatch, mock_aiohttp_session, first_status
):
    monitor, write = controlling_monitor
    await monitor._read_trades()
    write("renamed")
    monkeypatch.setattr(APP_CONFIG, "discord_bot_token", "")
    monkeypatch.setattr(APP_CONFIG, "discord_alert_channel_id", "")
    monkeypatch.setenv("WORLDOFTIME_WEBHOOK_URL", "https://discord.test/webhook")
    monitor.session = mock_aiohttp_session
    mock_aiohttp_session.post.return_value.__aenter__.side_effect = [
        AsyncMock(status=first_status), AsyncMock(status=204),
    ]
    with patch("monitor.DiscordApi.call", new=AsyncMock()) as bot:
        await monitor._read_trades()
        assert monitor.prices.trades_warned == (first_status == 204)
        await monitor._read_trades()
        await monitor._read_trades()
        bot.assert_not_awaited()

    assert monitor.prices.trades_warned
    assert mock_aiohttp_session.post.call_count == (1 if first_status == 204 else 2)
    for call in mock_aiohttp_session.post.call_args_list:
        assert call.args == ("https://discord.test/webhook",)
        message = call.kwargs["json"]["content"]
        assert "previous trades are still in use" in message
        assert "Missing CSV columns: EK" in message
        assert "Private Seller" not in message


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
        with patch("monitor.aiohttp.ClientSession") as mock_session_class:
            with patch("monitor.NotificationManager") as mock_notification_class:
                with patch("monitor.PersistenceManager") as mock_persistence_class:
                    with patch("monitor.SITE_CONFIGS", {"test_site": Mock()}):
                        with patch("monitor.SCRAPER_CLASSES", {"test_site": Mock()}):

                            mock_session = AsyncMock()
                            mock_session_class.return_value = mock_session

                            mock_persistence = Mock()
                            mock_persistence.load_seen_items.return_value = {
                                "test_site": {"id1", "id2"}
                            }
                            mock_persistence_class.return_value = mock_persistence

                            mock_scraper_class = Mock()
                            mock_scraper = Mock()
                            mock_scraper_class.return_value = mock_scraper

                            monitor = WatchMonitor()
                            await monitor.initialize()

                            assert monitor.session == mock_session
                            assert monitor.notification_manager is not None
                            assert "test_site" in monitor.seen_items
                            assert (
                                len(monitor.scrapers) > 0 or len(SCRAPER_CLASSES) == 0
                            )

    @pytest.mark.asyncio
    async def test_cleanup_preserves_history_after_initialization_failure(self, tmp_path):
        state_file = tmp_path / "seen_watches.json"
        backup_file = tmp_path / "seen_watches.json.bak"
        seed = {"shop": ["old"], "filter:111": ["offer1"]}
        for path in (state_file, backup_file):
            path.write_text(json.dumps(seed), encoding="utf-8")
        bad_prices = tmp_path / "prices.sqlite3"
        bad_prices.mkdir()

        with patch.multiple(
            APP_CONFIG,
            seen_watches_file=str(state_file),
            prices_file=str(bad_prices),
            enable_muv_actions=False,
            discord_interactions_enabled=False,
            muv_http_actions_enabled=False,
            muv_offer_link_urls=[],
        ):
            monitor = WatchMonitor(log_level="ERROR")
            try:
                with pytest.raises(sqlite3.OperationalError, match="unable to open database file"):
                    await monitor.initialize()
            finally:
                await monitor.cleanup()

        for path in (state_file, backup_file):
            assert json.loads(path.read_text(encoding="utf-8")) == seed

    @pytest.mark.asyncio
    async def test_cleanup(self):
        """Test monitor cleanup."""
        monitor = WatchMonitor()
        monitor.session = AsyncMock()
        monitor.session.closed = False
        session = monitor.session
        monitor.persistence = Mock()
        monitor.seen_items = {"site1": {"id1", "id2"}}

        await monitor.cleanup()

        session.close.assert_called_once()
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
            WatchData(
                title="Watch 1",
                url="https://example.com/1",
                site_name="Site 1",
                site_key="site1",
            ),
            WatchData(
                title="Watch 2",
                url="https://example.com/2",
                site_name="Site 1",
                site_key="site1",
            ),
        ]
        mock_scraper1.seen_ids = {"id1", "id2", "id3"}

        mock_scraper2 = AsyncMock()
        mock_scraper2.scrape.return_value = [
            WatchData(
                title="Watch 3",
                url="https://example.com/3",
                site_name="Site 2",
                site_key="site2",
            )
        ]
        mock_scraper2.seen_ids = {"id4"}

        monitor.scrapers = {"site1": mock_scraper1, "site2": mock_scraper2}

        # Mock seen items
        monitor.seen_items = {"site1": {"old_id1"}, "site2": set()}

        # Mock notification manager
        monitor.notification_manager = AsyncMock()
        monitor.notification_manager.send_notifications.return_value = 2

        # Mock persistence
        monitor.persistence = Mock()

        with patch(
            "monitor.SITE_CONFIGS",
            {"site1": Mock(name="Site 1"), "site2": Mock(name="Site 2")},
        ):
            with patch("monitor.APP_CONFIG") as mock_config:
                configure_monitor_config(mock_config, enable_notifications=True)

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
            WatchData(
                title="Watch 1",
                url="https://example.com/1",
                site_name="Site 1",
                site_key="site1",
            )
        ]
        mock_scraper1.seen_ids = {"id1"}

        mock_scraper2 = AsyncMock()
        mock_scraper2.scrape.side_effect = Exception("Scraping error")
        mock_scraper2.seen_ids = set()

        monitor.scrapers = {"site1": mock_scraper1, "site2": mock_scraper2}

        monitor.seen_items = {"site1": set(), "site2": set()}
        monitor.notification_manager = AsyncMock()
        monitor.notification_manager.send_notifications.return_value = 1
        monitor.persistence = Mock()

        with patch(
            "monitor.SITE_CONFIGS",
            {"site1": Mock(name="Site 1"), "site2": Mock(name="Site 2")},
        ):
            with patch("monitor.APP_CONFIG") as mock_config:
                configure_monitor_config(mock_config, enable_notifications=True)

                session = await monitor.run_monitoring_cycle()

        assert session.sites_scraped == 2
        assert session.errors_encountered == 1  # One scraper failed
        assert session.total_new_watches == 1  # Only successful scraper

    @pytest.mark.asyncio
    async def test_run_monitoring_cycle_notifications_disabled(self):
        """Test monitoring cycle with notifications disabled."""
        monitor = WatchMonitor()

        mock_scraper = AsyncMock()
        mock_scraper.scrape.return_value = [
            WatchData(
                title="Watch 1",
                url="https://example.com/1",
                site_name="Site 1",
                site_key="site1",
            )
        ]
        mock_scraper.seen_ids = {"id1"}

        monitor.scrapers = {"site1": mock_scraper}
        monitor.seen_items = {"site1": set()}
        monitor.notification_manager = AsyncMock()
        monitor.persistence = Mock()

        with patch("monitor.SITE_CONFIGS", {"site1": Mock(name="Site 1")}):
            with patch("monitor.APP_CONFIG") as mock_config:
                configure_monitor_config(
                    mock_config,
                    enable_notifications=False,
                    max_concurrent_scrapers=1,
                )

                session = await monitor.run_monitoring_cycle()

        assert session.notifications_sent == 0
        monitor.notification_manager.send_notifications.assert_not_called()

    @pytest.mark.asyncio
    async def test_scrape_single_site_success(self):
        """Test scraping a single site successfully."""
        monitor = WatchMonitor()

        mock_scraper = AsyncMock()
        new_watches = [
            WatchData(
                title="New Watch",
                url="https://example.com/new",
                site_name="Site 1",
                site_key="site1",
            )
        ]
        mock_scraper.scrape.return_value = new_watches
        mock_scraper.seen_ids = {"id1", "id2", "id3"}  # 3 total IDs

        session = ScrapingSession(session_id="test")
        monitor.seen_items = {"site1": {"id1"}}  # 1 previously seen
        monitor.notification_manager = AsyncMock()
        monitor.notification_manager.send_notifications.return_value = 1
        monitor.persistence = Mock()

        with patch("monitor.SITE_CONFIGS", {"site1": Mock(name="Site 1")}):
            with patch("monitor.APP_CONFIG") as mock_config:
                configure_monitor_config(mock_config, enable_notifications=True)

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

        with patch("monitor.APP_CONFIG") as mock_config:
            configure_monitor_config(mock_config, check_interval_seconds=0.01)

            await monitor.run_continuous()

        # Should have run at least one cycle
        monitor.run_monitoring_cycle.assert_called()
        assert monitor.running is False

    @pytest.mark.asyncio
    async def test_run_continuous_with_shutdown(self):
        """Test continuous monitoring with shutdown signal."""
        monitor = WatchMonitor()
        monitor.run_monitoring_cycle = AsyncMock(
            return_value=ScrapingSession(session_id="test")
        )

        # Simulate shutdown signal after short delay
        async def trigger_shutdown():
            await asyncio.sleep(0.01)
            monitor.shutdown_event.set()

        with patch("monitor.APP_CONFIG") as mock_config:
            configure_monitor_config(mock_config, check_interval_seconds=1)

            # Run both continuous monitoring and shutdown trigger
            await asyncio.gather(monitor.run_continuous(), trigger_shutdown())

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

        with patch("monitor.APP_CONFIG") as mock_config:
            configure_monitor_config(mock_config, check_interval_seconds=0.01)

            with patch("asyncio.sleep"):  # Mock sleep for error recovery
                await monitor.run_continuous()

        # Should continue after error
        assert monitor.run_monitoring_cycle.call_count >= 2

    @pytest.mark.asyncio
    async def test_validate_configuration_success(self):
        """Test configuration validation with valid setup."""
        monitor = WatchMonitor()
        monitor.notification_manager = AsyncMock()
        monitor.notification_manager.test_webhook.return_value = True

        with patch(
            "monitor.SITE_CONFIGS",
            {
                "site1": Mock(webhook_url="https://discord.com/webhooks/test1"),
                "site2": Mock(webhook_url="https://discord.com/webhooks/test2"),
            },
        ):
            with patch("monitor.SCRAPER_CLASSES", {"site1": Mock(), "site2": Mock()}):
                result = await monitor.validate_configuration()

        assert result is True
        assert monitor.notification_manager.test_webhook.call_count == 2

    @pytest.mark.asyncio
    async def test_validate_configuration_missing_scraper(self):
        """Test configuration validation with missing scraper."""
        monitor = WatchMonitor()
        monitor.notification_manager = AsyncMock()

        with patch(
            "monitor.SITE_CONFIGS",
            {
                "site1": Mock(webhook_url="https://discord.com/webhooks/test1"),
                "missing_scraper": Mock(
                    webhook_url="https://discord.com/webhooks/test2"
                ),
            },
        ):
            with patch(
                "monitor.SCRAPER_CLASSES",
                {
                    "site1": Mock()
                    # "missing_scraper" not in SCRAPER_CLASSES
                },
            ):
                result = await monitor.validate_configuration()

        assert result is False

    @pytest.mark.asyncio
    async def test_validate_configuration_missing_webhook(self):
        """Test configuration validation with missing webhook."""
        monitor = WatchMonitor()
        monitor.notification_manager = AsyncMock()

        with patch(
            "monitor.SITE_CONFIGS",
            {
                "site1": Mock(webhook_url="https://discord.com/webhooks/test1"),
                "site2": Mock(webhook_url=None),  # Missing webhook
            },
        ):
            with patch("monitor.SCRAPER_CLASSES", {"site1": Mock(), "site2": Mock()}):
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

        with patch(
            "monitor.SITE_CONFIGS",
            {"site1": Mock(webhook_url="https://discord.com/webhooks/invalid")},
        ):
            with patch("monitor.SCRAPER_CLASSES", {"site1": Mock()}):
                result = await monitor.validate_configuration()

        assert result is False

    def test_get_statistics(self):
        """Test getting monitoring statistics."""
        monitor = WatchMonitor()
        monitor.persistence = Mock()

        expected_stats = {
            "total_sessions": 10,
            "total_new_watches": 50,
            "success_rate": 90.0,
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
            price=Decimal("8500.00"),
        )
        mock_scraper.scrape.return_value = [new_watch]
        mock_scraper.seen_ids = {new_watch.composite_id}

        monitor.scrapers = {"test_site": mock_scraper}
        monitor.seen_items = {"test_site": set()}  # No previously seen items

        with patch(
            "monitor.SITE_CONFIGS",
            {
                "test_site": Mock(
                    name="Test Site", webhook_url="https://discord.com/test"
                )
            },
        ):
            with patch("monitor.APP_CONFIG") as mock_config:
                configure_monitor_config(
                    mock_config,
                    enable_notifications=True,
                    max_concurrent_scrapers=1,
                )

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
        at_once = {"now": 0, "most": 0}  # sites being scraped
        for i in range(5):
            scraper = AsyncMock()

            async def mock_scrape(delay=i * 0.01, index=i):
                at_once["now"] += 1
                at_once["most"] = max(at_once["most"], at_once["now"])
                await asyncio.sleep(delay)  # Simulate different response times
                at_once["now"] -= 1
                return [
                    WatchData(
                        title=f"Watch {index}",
                        url=f"https://example.com/watch{index}",
                        site_name=f"Site {index}",
                        site_key=f"site{index}",
                    )
                ]

            scraper.scrape = AsyncMock(side_effect=mock_scrape)
            scraper.seen_ids = {f"id{i}"}
            scrapers[f"site{i}"] = scraper

        monitor.scrapers = scrapers
        monitor.seen_items = {f"site{i}": set() for i in range(5)}
        monitor.notification_manager = AsyncMock()
        monitor.persistence = Mock()

        site_configs = {f"site{i}": Mock(name=f"Site {i}") for i in range(5)}

        with patch("monitor.SITE_CONFIGS", site_configs):
            with patch("monitor.APP_CONFIG") as mock_config:
                configure_monitor_config(
                    mock_config,
                    enable_notifications=False,
                    max_concurrent_scrapers=3,
                )

                session = await monitor.run_monitoring_cycle()

        # All sites should have been scraped
        assert session.sites_scraped == 5
        assert session.total_new_watches == 5

        # Sites are scraped side by side, and never more at once than the limit
        assert at_once["most"] == 3

        # Verify all scrapers were called
        for scraper in scrapers.values():
            scraper.scrape.assert_called_once()


@pytest.mark.parametrize("destination", ["webhook", "bot"])
@pytest.mark.parametrize("failure", ["5xx", "timeout", "rate_limited_twice"])
async def test_not_taken_alert_is_retried_next_cycle_only_until_posted(
    destination, failure, test_site_config, mock_aiohttp_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(APP_CONFIG, "enable_notifications", True)
    monkeypatch.setattr(APP_CONFIG, "enable_detail_scraping", False)
    monkeypatch.setattr(APP_CONFIG, "enable_muv_actions", False)
    monkeypatch.setattr(
        APP_CONFIG, "discord_bot_token", "bot-token" if destination == "bot" else ""
    )
    monkeypatch.setattr(APP_CONFIG, "discord_alert_channel_id", "")
    monkeypatch.setattr(APP_CONFIG, "seen_watches_file", str(tmp_path / "seen.json"))
    monkeypatch.setattr(APP_CONFIG, "session_history_file", str(tmp_path / "sessions.json"))
    monkeypatch.setattr(APP_CONFIG, "controlling_file", str(tmp_path / "absent.csv"))
    monkeypatch.setenv(test_site_config.webhook_env_var, "https://discord.test/webhook")

    config = test_site_config
    if destination == "bot":
        config = replace(config, key="filter:42", channel_id="42", webhook_env_var="")
    unposted, posted = [
        WatchData(
            title=title, url=f"https://example.com/{i}",
            site_name=config.name, site_key=config.key,
        )
        for i, title in enumerate(["Unposted", "Posted"], 1)
    ]

    class Shop(BaseScraper):
        async def _extract_watches(self, soup):
            # Duplicate cards still mean one alert for this listing.
            return [unposted, posted, unposted]

    def response(status):
        return AsyncMock(
            status=status, headers={"X-RateLimit-Reset-After": "0.512"},
            text=AsyncMock(return_value=json.dumps({"retry_after": 0.512})),
        )

    success_status = 201 if destination == "bot" else 204
    failures = {
        "5xx": [response(503)],
        "timeout": [asyncio.TimeoutError()],
        "rate_limited_twice": [response(429), response(429)],
    }
    mock_aiohttp_session.post.return_value.__aenter__.side_effect = (
        failures[failure] + [response(success_status), response(success_status)]
    )
    monitor = WatchMonitor(log_level="ERROR")
    monitor.filter_store = Mock()
    monitor.filter_store.all.return_value = []
    if destination == "bot":
        asked = Filter("42", "1", "kleinanzeigen", "private", "Rolex")
        monitor.filter_store.all.return_value = [asked]
        monitor.filters = {asked.key: asked}
        monitor.negotiator = Mock()
    monitor.notification_manager = NotificationManager(mock_aiohttp_session, monitor.logger)
    shop = Shop(config, logging.getLogger("test"))
    monitor.seen_items[config.key] = shop.seen_ids
    monitor.scrapers[config.key] = shop

    with patch("scrapers.base.fetch_page", return_value="<html></html>"), patch("asyncio.sleep") as waited:
        first = await monitor.run_monitoring_cycle()
        assert first.notifications_sent == 1
        assert unposted.composite_id not in shop.seen_ids
        assert list(shop.seen_ids) == [posted.composite_id]

        # The same delivery state survives restarting the scraper and loading its file.
        monitor.seen_items = monitor.persistence.load_seen_items()
        shop = Shop(config, logging.getLogger("test"))
        shop.set_seen_ids(monitor.seen_items[config.key])
        monitor.scrapers[config.key] = shop
        assert list(shop.seen_ids) == [posted.composite_id]

        second = await monitor.run_monitoring_cycle()
        assert second.notifications_sent == 1
        assert set(shop.seen_ids) == {unposted.composite_id, posted.composite_id}
        third = await monitor.run_monitoring_cycle()
        assert third.total_new_watches == third.notifications_sent == 0

    payloads = [call.kwargs["json"] for call in mock_aiohttp_session.post.call_args_list]
    assert [payload["embeds"][0]["title"] for payload in payloads] == (
        ["Unposted"] * len(failures[failure]) + ["Posted", "Unposted"]
    )
    if destination == "bot":
        for payload in payloads:
            button = payload["components"][0]["components"][0]
            assert button["label"] == "Negotiate"
            ad_id = "1" if payload["embeds"][0]["title"] == "Unposted" else "2"
            assert button["custom_id"] == f"negotiate:{ad_id}"
    if failure == "rate_limited_twice":
        assert sum(call.args == (0.512,) for call in waited.await_args_list) == 1


@pytest.mark.parametrize("unavailable", ["disabled", "no_destination"])
async def test_not_taken_without_notifications_stays_new_until_posted(
    unavailable, test_site_config, sample_watch_data, mock_aiohttp_session, monkeypatch
):
    monkeypatch.setattr(APP_CONFIG, "enable_notifications", unavailable != "disabled")
    monkeypatch.setattr(APP_CONFIG, "enable_detail_scraping", False)
    monkeypatch.setattr(APP_CONFIG, "enable_muv_actions", False)
    monkeypatch.setattr(APP_CONFIG, "discord_bot_token", "")
    monkeypatch.delenv(test_site_config.webhook_env_var, raising=False)
    mock_aiohttp_session.post.return_value.__aenter__.return_value.status = 204

    class Shop(BaseScraper):
        async def _extract_watches(self, soup):
            return [sample_watch_data]

    monitor = WatchMonitor(log_level="ERROR")
    monitor.persistence = Mock()
    monitor.notification_manager = NotificationManager(mock_aiohttp_session, monitor.logger)
    shop = Shop(test_site_config, logging.getLogger("test"))
    monitor.seen_items[shop.config.key] = shop.seen_ids

    with patch("scrapers.base.fetch_page", return_value="<html></html>"):
        await monitor._scrape_single_site(shop.config.key, shop, ScrapingSession())
        assert not shop.seen_ids
        mock_aiohttp_session.post.assert_not_called()

        monkeypatch.setattr(APP_CONFIG, "enable_notifications", True)
        monkeypatch.setenv(test_site_config.webhook_env_var, "https://discord.test/webhook")
        await monitor._scrape_single_site(shop.config.key, shop, ScrapingSession())
        assert list(shop.seen_ids) == [sample_watch_data.composite_id]
        await monitor._scrape_single_site(shop.config.key, shop, ScrapingSession())
        mock_aiohttp_session.post.assert_called_once()


@pytest.mark.parametrize("first_status", [201, 503])
async def test_not_taken_overlapping_filter_scans_do_not_post_twice(
    first_status, mock_aiohttp_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(APP_CONFIG, "enable_notifications", True)
    monkeypatch.setattr(APP_CONFIG, "enable_detail_scraping", False)
    monkeypatch.setattr(APP_CONFIG, "enable_muv_actions", False)
    monkeypatch.setattr(APP_CONFIG, "discord_bot_token", "bot-token")
    monkeypatch.setattr(APP_CONFIG, "seen_watches_file", str(tmp_path / "seen.json"))
    monkeypatch.setattr(APP_CONFIG, "session_history_file", str(tmp_path / "sessions.json"))
    monkeypatch.setattr(APP_CONFIG, "controlling_file", str(tmp_path / "absent.csv"))
    asked = Filter("42", "1", "kleinanzeigen", "private", "Rolex")
    monitor = WatchMonitor(log_level="ERROR")
    monitor.filter_store = Mock(all=Mock(return_value=[asked]))
    monitor.filters = {asked.key: asked}
    config = asked.scraper(monitor.logger).config
    watch = WatchData(
        title="Rolex", url="https://example.com/1",
        site_name=config.name, site_key=config.key,
    )

    class Shop(BaseScraper):
        async def _extract_watches(self, soup):
            return [watch]

    shop = Shop(config, monitor.logger)
    monitor.scrapers[asked.key] = shop
    monitor.seen_items[asked.key] = shop.seen_ids
    pending, release = asyncio.Event(), asyncio.Event()

    async def reply():
        first = mock_aiohttp_session.post.call_count == 1
        if first:
            pending.set()
            await release.wait()
        return AsyncMock(
            status=first_status if first else 201,
            text=AsyncMock(return_value=json.dumps({"id": "9"})),
        )

    mock_aiohttp_session.post.return_value.__aenter__.side_effect = reply
    monitor.notification_manager = NotificationManager(mock_aiohttp_session, monitor.logger)
    with patch("scrapers.base.fetch_page", return_value="<html></html>"):
        immediate = asyncio.create_task(monitor._scan_new_filter(asked))
        try:
            await asyncio.wait_for(pending.wait(), 2)
            await asyncio.wait_for(monitor.run_monitoring_cycle(), 2)
            mock_aiohttp_session.post.assert_called_once()
            assert not shop.seen_ids  # In flight is not successfully posted.
        finally:
            release.set()
            await immediate

        assert (watch.composite_id in shop.seen_ids) == (first_status == 201)
        # An overlapping scan neither repeats a successful post nor prevents a later retry.
        await monitor.run_monitoring_cycle()
        await monitor.run_monitoring_cycle()

    assert mock_aiohttp_session.post.call_count == (1 if first_status == 201 else 2)
    assert list(shop.seen_ids) == [watch.composite_id]


@pytest.mark.parametrize("first_status", [204, 503])
async def test_not_taken_notification_cli_remembers_only_successful_alerts(
    first_status, mock_aiohttp_session, tmp_path, monkeypatch
):
    from pathlib import Path
    from runpy import run_path

    # Load the CLI by path: pytest has a test module with the same filename.
    cli = run_path(str(Path(__file__).parents[1] / "test_notifications.py"))
    notify_single_scraper = cli["test_single_scraper"]

    monkeypatch.setattr(APP_CONFIG, "enable_notifications", True)
    monkeypatch.setattr(APP_CONFIG, "enable_detail_scraping", False)
    monkeypatch.setattr(APP_CONFIG, "enable_muv_actions", False)
    monkeypatch.setattr(APP_CONFIG, "discord_bot_token", "")
    monkeypatch.setattr(APP_CONFIG, "seen_watches_file", str(tmp_path / "seen.json"))
    config = SITE_CONFIGS["watch_out"]
    monkeypatch.setenv(config.webhook_env_var, "https://discord.test/webhook")
    watch = WatchData(
        title="Rolex", url="https://example.com/1",
        site_name=config.name, site_key=config.key,
    )

    class Shop(BaseScraper):
        async def _extract_watches(self, soup):
            return [watch]

    monitor = WatchMonitor(log_level="ERROR")
    shop = Shop(config, monitor.logger)
    monitor.scrapers[config.key] = shop
    monitor.seen_items[config.key] = shop.seen_ids
    mock_aiohttp_session.post.return_value.__aenter__.side_effect = [
        AsyncMock(status=first_status, text=AsyncMock(return_value="Unavailable")),
        AsyncMock(status=204),
    ]
    monitor.notification_manager = NotificationManager(mock_aiohttp_session, monitor.logger)
    with patch("scrapers.base.fetch_page", return_value="<html></html>"):
        assert await notify_single_scraper(monitor, config.key)
        remembered = monitor.persistence.load_seen_items()[config.key]
        assert list(remembered) == ([watch.composite_id] if first_status == 204 else [])
        shop.set_seen_ids(remembered)
        await monitor._scrape_single_site(config.key, shop, ScrapingSession())
        await monitor._scrape_single_site(config.key, shop, ScrapingSession())

    assert mock_aiohttp_session.post.call_count == (1 if first_status == 204 else 2)
    assert list(shop.seen_ids) == [watch.composite_id]


@pytest.mark.parametrize("price_text,pressed,expired,removed", [
    ("9000 €", True, False, False),
    ("17790 €", True, False, False),
    ("VB", True, False, False),
    ("9000 €", True, True, False),
    ("9000 €", True, False, True),
    ("9000 €", False, False, False),
])
async def test_press_kept_until_prices_come_after_restart(price_text, pressed, expired, removed, tmp_path, monkeypatch):
    store = FilterStore(tmp_path / "filters.json")
    store.add(Filter("42", "1", "kleinanzeigen", "private", "Rolex"))
    watch = WatchData(title="Rolex", url="https://www.kleinanzeigen.de/s-anzeige/123",
                      site_name="Kleinanzeigen", site_key="filter:42")
    reading = Reading(is_watch_for_sale=True, brand="Rolex", model="Submariner", reference="116610LV",
                      year=None, condition="good", box=True, papers=True)
    read = AsyncMock(return_value=reading)
    monkeypatch.setattr("agent.read", read)

    def monitor_with(fetch):
        monitor = WatchMonitor(log_level="ERROR")
        monitor.persistence = Mock()
        monitor.filter_store = store
        monitor._sync_filters()
        monitor._read_trades = AsyncMock()
        monitor._scrape_single_site = AsyncMock()
        monitor.prices = Prices(tmp_path / "prices.sqlite3")
        monitor.deals = Deals(tmp_path / "deals.sqlite3")
        monitor._tell_owner = AsyncMock()
        monitor.negotiator = Negotiator(None, Negotiations(tmp_path / "deals.sqlite3"),
                                        monitor._tell_owner, monitor.logger)
        monitor.agent = Agent(None, fetch, monitor.prices, monitor.deals, monitor.logger,
                              monitor._negotiate_if_asked, monitor._negotiate_by_hand, monitor._tell_owner)
        return monitor

    monitor = monitor_with(AsyncMock(return_value=f'<h1 id="viewad-title">Rolex</h1>'
                                                f'<h2 id="viewad-price">{price_text}</h2>'))
    try:
        if pressed:
            monitor._negotiate_pressed({"data": {"custom_id": "negotiate:123"}, "channel_id": "42"})
            await asyncio.gather(*monitor._judging)
            monitor._tell_owner.assert_awaited_once_with(
                watch.site_key, f"The agent leaves {watch.url} alone: too few Chrono24 offers for 116610LV yet."
            )
        else:
            await monitor.agent.consider([watch])
            monitor._tell_owner.assert_not_awaited()
        assert monitor.negotiator.negotiations.with_status("pending") == []
        if expired:
            with monitor.deals._db:
                monitor.deals._db.execute(
                    "UPDATE verdicts SET judged = ?", ((datetime.now() - timedelta(days=8)).isoformat(timespec="seconds"),)
                )
    finally:
        await monitor.cleanup()

    if removed:
        store.remove("42")
    fetch = AsyncMock()
    restarted = monitor_with(fetch)
    try:
        offers = [WatchData(title="Rolex", url=f"https://www.chrono24.de/{number}", site_name="Chrono24",
                            site_key="chrono24", reference="116610LV", price=Decimal("10800"))
                  for number in range(5)]
        restarted.prices.searched("116610LV", USED, len(offers), offers, datetime.now())
        await restarted.run_monitoring_cycle()
        await asyncio.gather(*restarted._judging)
        assert restarted.negotiator.negotiations.with_status("pending") == []
        restarted._tell_owner.assert_not_awaited()  # Full sets still await their own search.

        restarted.prices.searched("116610LV", FULL_SET, 0, [], datetime.now())
        for _ in range(2):
            await restarted.run_monitoring_cycle()
            await asyncio.gather(*restarted._judging)
        pending = restarted.negotiator.negotiations.with_status("pending")
        if pressed and not (expired or removed):
            (negotiation,) = pending
            assert (negotiation.ad_id, negotiation.channel, negotiation.limit, negotiation.offered) == (
                "123", watch.site_key, 8608, 7550,
            )
            assert negotiation.asking == (None if price_text == "VB" else int(price_text.split()[0]))
            restarted._tell_owner.assert_awaited_once_with(
                watch.site_key, f"The agent negotiates on {watch.url}: it opens at 7.550 € and pays 8.608 € at most."
            )
        else:
            assert pending == []
            restarted._tell_owner.assert_not_awaited()
        fetch.assert_not_awaited()
        read.assert_awaited_once()
    finally:
        await restarted.cleanup()


@pytest.mark.parametrize("requested", [False, True])
@pytest.mark.parametrize("removed", ["never", "before_restart", "during_read"])
async def test_owed_a_verdict_survives_cleanup_but_only_negotiates_while_the_filter_exists(
    requested, removed, tmp_path, monkeypatch
):
    monkeypatch.setattr(APP_CONFIG, "enable_notifications", True)
    monkeypatch.setattr(APP_CONFIG, "controlling_file", str(tmp_path / "absent.csv"))
    asked = Filter("42", "1", "kleinanzeigen", "private", "Rolex", negotiate=not requested)
    store = FilterStore(tmp_path / "filters.json")
    store.add(asked)
    watch = WatchData(title="Rolex", url="https://www.kleinanzeigen.de/s-anzeige/123",
                      site_name="Kleinanzeigen", site_key=asked.key, price=Decimal("9000"))
    reading = Reading(is_watch_for_sale=True, brand="Rolex", model="Submariner", reference="116610LN",
                      year=None, condition="good", box=False, papers=False)
    read = AsyncMock(return_value=reading)
    monkeypatch.setattr("agent.read", read)
    entered = asyncio.Event()

    async def interrupted(url):
        entered.set()
        await asyncio.Future()

    def monitor_with(fetch):
        monitor = WatchMonitor(log_level="ERROR")
        monitor.persistence = Mock()
        monitor.filter_store = store
        monitor.filters = {f.key: f for f in store.all()}
        monitor.prices = Prices(tmp_path / "prices.sqlite3")
        monitor.prices.set_buy_price("116610LN", 8600, datetime.now())
        monitor.deals = Deals(tmp_path / "deals.sqlite3")
        monitor._tell_owner = AsyncMock()
        monitor.negotiator = Negotiator(None, Negotiations(tmp_path / "deals.sqlite3"),
                                        monitor._tell_owner, monitor.logger)
        monitor.agent = Agent(None, fetch, monitor.prices, monitor.deals, monitor.logger,
                              monitor._negotiate_if_asked, monitor._negotiate_by_hand, monitor._tell_owner)
        monitor.notification_manager = AsyncMock()
        return monitor

    monitor = monitor_with(interrupted)
    scraper = Mock(config=asked.scraper(monitor.logger).config, scrape=AsyncMock(return_value=[watch]),
                   seen_ids=SeenIds(), last_scan=[])

    async def alert(watches, config, **kwargs):
        # The obligation is committed before the alert can mark the match seen, even before its task runs.
        assert monitor.deals.judging(watch) is not None
        kwargs["seen_ids"].add(watch.composite_id)
        return 1

    monitor.notification_manager.send_notifications.side_effect = alert
    try:
        await monitor._scrape_single_site(asked.key, scraper, ScrapingSession())
        await asyncio.wait_for(entered.wait(), 2)
        assert watch.composite_id in monitor.seen_items[asked.key]
        monitor.persistence.save_seen_items.assert_called_once()
        if requested:
            reply = monitor._negotiate_pressed({"data": {"custom_id": "negotiate:123"}, "channel_id": "42"})
            assert "reads the offer again" in reply
    finally:
        await monitor.cleanup()
    assert not monitor._judging

    # No new match arrives in the next process. Only the saved claim can start this deal.
    if removed == "before_restart":
        store.remove(asked.channel_id)
    price = "17790" if requested else "9000"

    async def page(url):
        if removed == "during_read":
            store.remove(asked.channel_id)
            restarted._sync_filters()
        return f'<h1 id="viewad-title">Rolex</h1><h2 id="viewad-price">{price} €</h2>'

    fetch = AsyncMock(side_effect=page)
    restarted = monitor_with(fetch)
    try:
        await restarted.run_monitoring_cycle()
        await asyncio.gather(*restarted._judging)
        pending = restarted.negotiator.negotiations.with_status("pending")
        if removed == "never":
            (negotiation,) = pending
            assert (negotiation.ad_id, negotiation.channel, negotiation.limit, negotiation.asking) == (
                "123", "filter:42", 8600, int(price),
            )
        else:
            assert pending == []
        if removed == "before_restart":
            assert restarted.deals.judging(watch)["attempts"] == 1
        else:
            assert restarted.deals.owed() == []
        await restarted.run_monitoring_cycle()
        await asyncio.gather(*restarted._judging)
        expected_reads = int(removed != "before_restart")
        assert fetch.await_count == read.await_count == expected_reads
        assert restarted._tell_owner.await_count == int(requested and removed == "never")
        restarted.notification_manager.send_notifications.assert_not_called()
    finally:
        await restarted.cleanup()


@pytest.mark.parametrize("during_tend", [False, True])
async def test_owed_a_verdict_manual_request_before_the_initial_filter_sync_is_completed(
    during_tend, tmp_path, monkeypatch
):
    monitor = WatchMonitor(log_level="ERROR")
    monitor.filter_store = FilterStore(tmp_path / "filters.json")
    monitor.filter_store.add(Filter("42", "1", "kleinanzeigen", "private", "Rolex"))
    monitor.persistence = Mock()
    monitor._read_trades = AsyncMock()
    monitor._scrape_single_site = AsyncMock()
    monitor.prices = Prices(tmp_path / "prices.sqlite3")
    monitor.prices.set_buy_price("116610LN", 8600, datetime.now())
    monitor.deals = Deals(tmp_path / "deals.sqlite3")
    monitor._tell_owner = AsyncMock()
    monitor.negotiator = Negotiator(None, Negotiations(tmp_path / "deals.sqlite3"),
                                    monitor._tell_owner, monitor.logger)
    fetch = AsyncMock(return_value='<h1 id="viewad-title">Rolex</h1><h2 id="viewad-price">9000 €</h2>')
    reading = Reading(is_watch_for_sale=True, brand="Rolex", model="Submariner", reference="116610LN",
                      year=None, condition="good", box=False, papers=False)
    monkeypatch.setattr("agent.read", AsyncMock(return_value=reading))
    monitor.agent = Agent(None, fetch, monitor.prices, monitor.deals, monitor.logger,
                          monitor._negotiate_if_asked, monitor._negotiate_by_hand, monitor._tell_owner)
    entered, release = asyncio.Event(), asyncio.Event()

    async def tend():
        entered.set()
        await release.wait()

    monitor.filter_flow = Mock(tend=AsyncMock(side_effect=tend))
    cycle = None
    try:
        if during_tend:
            cycle = asyncio.create_task(monitor.run_monitoring_cycle())
            await asyncio.wait_for(entered.wait(), 2)
        assert monitor.filters == {}
        monitor._negotiate_pressed({"data": {"custom_id": "negotiate:123"}, "channel_id": "42"})
        await asyncio.gather(*monitor._judging)
        (negotiation,) = monitor.negotiator.negotiations.with_status("pending")
        assert (negotiation.ad_id, negotiation.channel, negotiation.limit) == ("123", "filter:42", 8600)
        monitor._tell_owner.assert_awaited_once()
        assert monitor.deals.owed() == []
        release.set()
        if cycle is not None:
            await cycle
        await monitor.run_monitoring_cycle()
        await asyncio.gather(*monitor._judging)
        fetch.assert_awaited_once()
        monitor._tell_owner.assert_awaited_once()
    finally:
        release.set()
        if cycle is not None:
            await asyncio.gather(cycle, return_exceptions=True)
        await monitor.cleanup()
