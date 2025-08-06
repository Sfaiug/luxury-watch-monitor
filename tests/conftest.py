"""Pytest configuration and fixtures for watch monitor tests."""

import pytest
import asyncio
import tempfile
import shutil
import json
import logging
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch
from typing import Dict, Any, List
from decimal import Decimal
from datetime import datetime
import aiohttp

# Import actual modules from the codebase
from models import WatchData, ScrapingSession
from config import SiteConfig, APP_CONFIG, SITE_CONFIGS
from persistence import PersistenceManager
from notifications import NotificationManager
from scrapers.base import BaseScraper
from scrapers.worldoftime import WorldOfTimeScraper


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    shutil.rmtree(temp_path, ignore_errors=True)


@pytest.fixture
def test_config(temp_dir):
    """Test application configuration."""
    config = APP_CONFIG
    # Override with test-specific values
    config.seen_watches_file = str(temp_dir / "test_seen_watches.json")
    config.session_history_file = str(temp_dir / "test_session_history.json")
    config.check_interval_seconds = 5  # Shorter for tests
    config.max_retries = 2
    config.request_timeout = 5
    config.enable_notifications = False  # Disable by default for tests
    return config


@pytest.fixture
def test_site_config():
    """Test site configuration."""
    return SiteConfig(
        name="Test Site",
        key="test_site",
        url="https://example.com/watches",
        webhook_env_var="TEST_WEBHOOK_URL",
        color=0x00FF00,
        base_url="https://example.com",
        watch_container_selector="div.watch-item",
        title_selector="h3.title",
        price_selector="span.price",
        link_selector="a.watch-link",
        image_selector="img.watch-image",
        known_brands={"rolex": "Rolex", "omega": "Omega"}
    )


@pytest.fixture
def sample_watch_data():
    """Sample watch data for testing."""
    return WatchData(
        title="Rolex Submariner Date 116610LN",
        url="https://example.com/watches/submariner-116610ln",
        site_name="Test Site",
        site_key="test_site",
        brand="Rolex",
        model="Submariner",
        reference="116610LN",
        year="2020",
        price=Decimal("8500.00"),
        currency="EUR",
        image_url="https://example.com/images/submariner.jpg",
        condition="★★★★★",
        has_papers=True,
        has_box=True,
        case_material="Stainless Steel",
        diameter="40mm"
    )


@pytest.fixture
def sample_watch_list():
    """List of sample watches for testing."""
    watches = []
    
    # Create variations of watches
    for i in range(3):
        watch = WatchData(
            title=f"Rolex Submariner {116610 + i}",
            url=f"https://example.com/watches/submariner-{116610 + i}",
            site_name="Test Site",
            site_key="test_site",
            brand="Rolex",
            model="Submariner",
            reference=f"{116610 + i}",
            year=str(2020 - i),
            price=Decimal(str(8500.00 + (i * 100))),
            currency="EUR",
            condition="★★★★★"
        )
        watches.append(watch)
    
    return watches


@pytest.fixture
def sample_scraping_session():
    """Sample scraping session for testing."""
    session = ScrapingSession(session_id="test-session-123")
    session.add_site_result(
        site_key="test_site",
        total_found=10,
        new_found=3,
        notifications=2,
        errors=0
    )
    session.finalize()
    return session


@pytest.fixture
def mock_logger():
    """Mock logger for testing."""
    return Mock(spec=logging.Logger)


@pytest.fixture
def mock_aiohttp_session():
    """Mock aiohttp session for testing."""
    session = AsyncMock(spec=aiohttp.ClientSession)
    
    # Mock successful response
    response = AsyncMock()
    response.status = 200
    response.text = AsyncMock(return_value="<html><body>Test HTML</body></html>")
    response.json = AsyncMock(return_value={"rates": {"EUR": 0.85}})
    response.raise_for_status = Mock()
    response.headers = {"X-RateLimit-Reset-After": "5"}
    
    # Mock context manager behavior
    session.get.return_value.__aenter__.return_value = response
    session.post.return_value.__aenter__.return_value = response
    session.close = AsyncMock()
    
    return session


@pytest.fixture
def mock_beautiful_soup():
    """Mock BeautifulSoup parsing for testing."""
    from bs4 import BeautifulSoup
    
    # Create mock HTML structure
    html = """
    <div class="watch-item">
        <h3 class="title"><a href="/watch1">Rolex Submariner</a></h3>
        <span class="price">€8,500</span>
        <img class="watch-image" src="/images/submariner.jpg" alt="Rolex">
        <div class="description">Excellent condition with box and papers</div>
    </div>
    <div class="watch-item">
        <h3 class="title"><a href="/watch2">Omega Speedmaster</a></h3>
        <span class="price">€4,200</span>
        <img class="watch-image" src="/images/speedmaster.jpg" alt="Omega">
        <div class="description">Good condition, service history available</div>
    </div>
    """
    
    return BeautifulSoup(html, 'html.parser')


@pytest.fixture
def test_persistence_manager(mock_logger, temp_dir):
    """Test persistence manager instance."""
    # Temporarily patch the config paths
    with patch('persistence.APP_CONFIG') as mock_config:
        mock_config.seen_watches_file = str(temp_dir / "test_seen_watches.json")
        mock_config.session_history_file = str(temp_dir / "test_session_history.json")
        mock_config.max_seen_items_per_site = 1000
        mock_config.session_history_retention_days = 30
        
        manager = PersistenceManager(mock_logger)
        return manager


@pytest.fixture
def mock_notification_manager(mock_aiohttp_session, mock_logger):
    """Mock notification manager for testing."""
    manager = NotificationManager(mock_aiohttp_session, mock_logger)
    manager._send_single_notification = AsyncMock(return_value=True)
    return manager


@pytest.fixture
def sample_html_response():
    """Sample HTML response for scraper testing."""
    return """
    <!DOCTYPE html>
    <html>
    <body>
        <div class="watch-listings">
            <div class="watch-item" data-id="123">
                <h3 class="title">
                    <a href="/watches/rolex-submariner-116610ln">Rolex Submariner Date</a>
                </h3>
                <span class="price">€8,500.00</span>
                <img class="watch-image" src="/images/submariner.jpg" alt="Rolex Submariner">
                <div class="description">
                    Black dial, ceramic bezel, year 2020, excellent condition
                </div>
                <div class="specifications">
                    <span class="reference">Ref: 116610LN</span>
                    <span class="diameter">40mm</span>
                    <span class="material">Stainless Steel</span>
                </div>
            </div>
            <div class="watch-item" data-id="456">
                <h3 class="title">
                    <a href="/watches/omega-speedmaster-311">Omega Speedmaster Professional</a>
                </h3>
                <span class="price">€4,200.00</span>
                <img class="watch-image" src="/images/speedmaster.jpg" alt="Omega Speedmaster">
                <div class="description">
                    Moonwatch, manual wind, year 2019, very good condition
                </div>
                <div class="specifications">
                    <span class="reference">Ref: 311.30.42.30.01.005</span>
                    <span class="diameter">42mm</span>
                    <span class="material">Steel</span>
                </div>
            </div>
        </div>
    </body>
    </html>
    """


@pytest.fixture
def environment_variables(monkeypatch):
    """Set up test environment variables."""
    test_env = {
        "WORLDOFTIME_WEBHOOK_URL": "https://discord.com/api/webhooks/test/token1",
        "GRIMMEISSEN_WEBHOOK_URL": "https://discord.com/api/webhooks/test/token2",
        "TROPICALWATCH_WEBHOOK_URL": "https://discord.com/api/webhooks/test/token3",
        "WATCH_MONITOR_LOG_LEVEL": "DEBUG",
        "WATCH_MONITOR_CHECK_INTERVAL": "60"
    }
    
    for key, value in test_env.items():
        monkeypatch.setenv(key, value)
    
    return test_env


# Test data generators
def create_test_watch(
    title: str = "Test Watch",
    price: float = 1000.0,
    brand: str = "TestBrand",
    **kwargs: Any
) -> WatchData:
    """Create a test watch with specified parameters."""
    defaults = {
        "url": f"https://example.com/watches/{title.lower().replace(' ', '-')}",
        "site_name": "Test Site",
        "site_key": "test_site",
        "brand": brand,
        "currency": "EUR",
        "condition": "★★★☆☆"
    }
    defaults.update(kwargs)
    
    return WatchData(title=title, price=Decimal(str(price)), **defaults)


def create_test_scraping_session(
    session_id: str = "test-session",
    site_key: str = "test_site",
    total_found: int = 10,
    new_found: int = 2,
    notifications: int = 1,
    errors: int = 0
) -> ScrapingSession:
    """Create a test scraping session."""
    session = ScrapingSession(session_id=session_id)
    session.add_site_result(site_key, total_found, new_found, notifications, errors)
    session.finalize()
    return session


@pytest.fixture
def mock_base_scraper(test_site_config, mock_aiohttp_session, mock_logger):
    """Mock base scraper for testing."""
    scraper = Mock(spec=BaseScraper)
    scraper.config = test_site_config
    scraper.session = mock_aiohttp_session
    scraper.logger = Mock()
    scraper.logger.logger = mock_logger
    scraper.seen_ids = set()
    scraper.scrape = AsyncMock(return_value=[])
    scraper.set_seen_ids = Mock()
    return scraper


@pytest.fixture
def sample_html_content():
    """Sample HTML content for scraper testing."""
    return """
    <html>
        <body>
            <div class="watch-item">
                <h3 class="title">
                    <a href="/watches/rolex-submariner">Rolex Submariner Date</a>
                </h3>
                <span class="price">€8,500.00</span>
                <img class="watch-image" src="/images/submariner.jpg" alt="Rolex">
            </div>
            <div class="watch-item">
                <h3 class="title">
                    <a href="/watches/omega-speedmaster">Omega Speedmaster</a>
                </h3>
                <span class="price">€4,200.00</span>
                <img class="watch-image" src="/images/speedmaster.jpg" alt="Omega">
            </div>
        </body>
    </html>
    """


# Test utilities
class AsyncContextManagerMock:
    """Mock async context manager for testing."""
    
    def __init__(self, return_value=None):
        self.return_value = return_value
    
    async def __aenter__(self):
        return self.return_value
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


@pytest.fixture
def discord_webhook_response():
    """Mock Discord webhook response."""
    response = AsyncMock()
    response.status = 204  # Discord success status
    response.text = AsyncMock(return_value="")
    response.headers = {}
    return response