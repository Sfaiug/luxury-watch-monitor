"""Tests for scraper implementations."""

import pytest
import asyncio
from unittest.mock import AsyncMock, Mock, patch
from bs4 import BeautifulSoup
from decimal import Decimal

from scrapers.base import BaseScraper
from scrapers.worldoftime import WorldOfTimeScraper
from models import WatchData
from config import SiteConfig


class TestBaseScraper:
    """Test BaseScraper abstract class functionality."""
    
    def test_base_scraper_initialization(self, test_site_config, mock_aiohttp_session, mock_logger):
        """Test BaseScraper initialization."""
        # Create a concrete implementation for testing
        class ConcreteScraper(BaseScraper):
            async def _extract_watches(self, soup):
                return []
        
        scraper = ConcreteScraper(test_site_config, mock_aiohttp_session, mock_logger)
        
        assert scraper.config == test_site_config
        assert scraper.session == mock_aiohttp_session
        assert len(scraper.seen_ids) == 0
    
    @pytest.mark.asyncio
    async def test_scrape_success(self, test_site_config, mock_aiohttp_session, mock_logger, sample_html_content):
        """Test successful scraping."""
        class TestScraper(BaseScraper):
            async def _extract_watches(self, soup):
                return [
                    WatchData(
                        title="Test Watch 1",
                        url="https://example.com/watch1",
                        site_name=self.config.name,
                        site_key=self.config.key
                    ),
                    WatchData(
                        title="Test Watch 2", 
                        url="https://example.com/watch2",
                        site_name=self.config.name,
                        site_key=self.config.key
                    )
                ]
        
        scraper = TestScraper(test_site_config, mock_aiohttp_session, mock_logger)
        
        # Mock fetch_page to return HTML content
        with patch('scrapers.base.fetch_page', return_value=sample_html_content):
            with patch('scrapers.base.APP_CONFIG') as mock_config:
                mock_config.enable_detail_scraping = False
                
                result = await scraper.scrape()
        
        assert len(result) == 2
        assert result[0].title == "Test Watch 1"
        assert result[1].title == "Test Watch 2"
        assert len(scraper.seen_ids) == 2
    
    @pytest.mark.asyncio
    async def test_scrape_with_seen_watches(self, test_site_config, mock_aiohttp_session, mock_logger, sample_html_content):
        """Test scraping with some watches already seen."""
        class TestScraper(BaseScraper):
            async def _extract_watches(self, soup):
                return [
                    WatchData(
                        title="New Watch",
                        url="https://example.com/new",
                        site_name=self.config.name,
                        site_key=self.config.key
                    ),
                    WatchData(
                        title="Seen Watch",
                        url="https://example.com/seen", 
                        site_name=self.config.name,
                        site_key=self.config.key
                    )
                ]
        
        scraper = TestScraper(test_site_config, mock_aiohttp_session, mock_logger)
        
        # Pre-populate seen IDs with one watch
        seen_watch = WatchData(
            title="Seen Watch",
            url="https://example.com/seen",
            site_name=test_site_config.name,
            site_key=test_site_config.key
        )
        scraper.seen_ids = {seen_watch.composite_id}
        
        with patch('scrapers.base.fetch_page', return_value=sample_html_content):
            with patch('scrapers.base.APP_CONFIG') as mock_config:
                mock_config.enable_detail_scraping = False
                
                result = await scraper.scrape()
        
        # Should only return the new watch
        assert len(result) == 1
        assert result[0].title == "New Watch"
    
    @pytest.mark.asyncio
    async def test_scrape_fetch_page_failure(self, test_site_config, mock_aiohttp_session, mock_logger):
        """Test scraping when page fetch fails."""
        class TestScraper(BaseScraper):
            async def _extract_watches(self, soup):
                return []
        
        scraper = TestScraper(test_site_config, mock_aiohttp_session, mock_logger)
        
        with patch('scrapers.base.fetch_page', return_value=None):
            result = await scraper.scrape()
        
        assert result == []
    
    @pytest.mark.asyncio
    async def test_scrape_with_detail_fetching(self, test_site_config, mock_aiohttp_session, mock_logger, sample_html_content):
        """Test scraping with detail page fetching enabled.""" 
        class TestScraper(BaseScraper):
            async def _extract_watches(self, soup):
                return [
                    WatchData(
                        title="Test Watch",
                        url="https://example.com/watch",
                        site_name=self.config.name,
                        site_key=self.config.key
                    )
                ]
            
            async def _extract_watch_details(self, watch, soup):
                watch.reference = "123456"
                watch.year = "2020"
        
        scraper = TestScraper(test_site_config, mock_aiohttp_session, mock_logger)
        
        with patch('scrapers.base.fetch_page', return_value=sample_html_content):
            with patch('scrapers.base.APP_CONFIG') as mock_config:
                mock_config.enable_detail_scraping = True
                mock_config.detail_page_delay = 0.01  # Fast for testing
                mock_config.max_concurrent_details = 2
                
                result = await scraper.scrape()
        
        assert len(result) == 1
        assert result[0].detail_scraped is True
        assert result[0].reference == "123456"
        assert result[0].year == "2020"
    
    @pytest.mark.asyncio
    async def test_scrape_extraction_error(self, test_site_config, mock_aiohttp_session, mock_logger, sample_html_content):
        """Test scraping when watch extraction raises an error."""
        class TestScraper(BaseScraper):
            async def _extract_watches(self, soup):
                raise Exception("Extraction error")
        
        scraper = TestScraper(test_site_config, mock_aiohttp_session, mock_logger)
        
        with patch('scrapers.base.fetch_page', return_value=sample_html_content):
            result = await scraper.scrape()
        
        assert result == []
    
class TestWorldOfTimeScraper:
    """Test WorldOfTimeScraper implementation."""
    
    def test_worldoftime_scraper_initialization(self, mock_aiohttp_session, mock_logger):
        """Test WorldOfTimeScraper initialization."""
        config = SiteConfig(
            name="World of Time",
            key="worldoftime",
            url="https://www.worldoftime.de/Watches/NewArrivals",
            webhook_env_var="WORLDOFTIME_WEBHOOK_URL",
            color=0x2F4F4F,
            base_url="https://www.worldoftime.de",
            watch_container_selector="div.watch-item",
            link_selector="a.watch-link",
            title_selector="h3.title",
            price_selector="span.price",
            image_selector="img.watch-image",
            known_brands={"rolex": "Rolex", "omega": "Omega"}
        )
        
        scraper = WorldOfTimeScraper(config, mock_aiohttp_session, mock_logger)
        
        assert scraper.config == config
        assert isinstance(scraper, BaseScraper)
    
    @pytest.mark.asyncio
    async def test_extract_watches_no_elements(self, mock_aiohttp_session, mock_logger):
        """Test watch extraction when no watch elements are found."""
        config = SiteConfig(
            name="World of Time",
            key="worldoftime",
            url="https://www.worldoftime.de/Watches/NewArrivals", 
            webhook_env_var="WORLDOFTIME_WEBHOOK_URL",
            color=0x2F4F4F,
            base_url="https://www.worldoftime.de",
            watch_container_selector="div.watch-item",
            link_selector="a",
            title_selector="h3.title",
            price_selector="span.price",
            image_selector="img"
        )
        
        html_content = "<div class='no-watches'>No watches found</div>"
        
        scraper = WorldOfTimeScraper(config, mock_aiohttp_session, mock_logger)  
        soup = BeautifulSoup(html_content, 'html.parser')
        
        result = await scraper._extract_watches(soup)
        
        assert result == []
    
    @pytest.mark.asyncio
    async def test_extract_watches_missing_elements(self, mock_aiohttp_session, mock_logger):
        """Test watch extraction with missing required elements."""
        config = SiteConfig(
            name="World of Time",
            key="worldoftime",
            url="https://www.worldoftime.de/Watches/NewArrivals",
            webhook_env_var="WORLDOFTIME_WEBHOOK_URL", 
            color=0x2F4F4F,
            base_url="https://www.worldoftime.de",
            watch_container_selector="div.watch-item",
            link_selector="a.missing",  # Missing selector
            title_selector="h3.title",
            price_selector="span.price",
            image_selector="img"
        )
        
        html_content = """
        <div class="watch-item">
            <h3 class="title">Rolex Submariner</h3>
            <span class="price">€8,500.00</span>
        </div>
        """
        
        scraper = WorldOfTimeScraper(config, mock_aiohttp_session, mock_logger)
        soup = BeautifulSoup(html_content, 'html.parser')
        
        result = await scraper._extract_watches(soup)
        
        assert result == []  # Should skip watches without required elements
    
    @pytest.mark.asyncio
    async def test_extract_watch_details_no_table(self, mock_aiohttp_session, mock_logger):
        """Test detail extraction when no table is found."""
        config = SiteConfig(
            name="World of Time",
            key="worldoftime",
            url="https://www.worldoftime.de/Watches/NewArrivals",
            webhook_env_var="WORLDOFTIME_WEBHOOK_URL",
            color=0x2F4F4F,
            base_url="https://www.worldoftime.de",
            detail_page_selectors={"table": "table.missing"}
        )
        
        detail_html = "<html><body>No table here</body></html>"
        
        watch = WatchData(
            title="Test Watch",
            url="https://example.com/watch",
            site_name="World of Time",
            site_key="worldoftime"
        )
        
        scraper = WorldOfTimeScraper(config, mock_aiohttp_session, mock_logger)
        soup = BeautifulSoup(detail_html, 'html.parser')
        
        # Should not raise an error
        await scraper._extract_watch_details(watch, soup)
        
        # Watch should remain unchanged
        assert watch.reference is None
        assert watch.year is None
    