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
    
    def test_set_seen_ids(self, mock_base_scraper):
        """Test setting seen IDs."""
        seen_ids = {"id1", "id2", "id3"}
        mock_base_scraper.set_seen_ids(seen_ids)
        
        assert mock_base_scraper.seen_ids == seen_ids
    
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
    
    def test_parse_price_text(self, mock_base_scraper):
        """Test price text parsing from elements."""
        # Mock element with text
        element = Mock()
        element.get_text.return_value = "€8,500.00"
        
        result = mock_base_scraper._parse_price_text(element)
        assert result == "€8,500.00"
        
        # Mock element with data attribute
        element2 = Mock()
        element2.get_text.return_value = ""
        element2.attrs = {"data-price": "10000"}
        
        result2 = mock_base_scraper._parse_price_text(element2)
        assert result2 == "10000"
        
        # Test with None element
        result3 = mock_base_scraper._parse_price_text(None)
        assert result3 is None
    
    def test_extract_brand_model(self, test_site_config, mock_aiohttp_session, mock_logger):
        """Test brand and model extraction from titles."""
        scraper = BaseScraper(test_site_config, mock_aiohttp_session, mock_logger)
        scraper.__class__ = type('ConcreteScraper', (BaseScraper,), {
            '_extract_watches': lambda self, soup: []
        })
        
        # Test with known brand
        brand, model = scraper._extract_brand_model("Rolex Submariner Date")
        assert brand == "Rolex"
        assert model == "Submariner Date"
        
        # Test with brand not in config
        brand, model = scraper._extract_brand_model("UnknownBrand Model X")
        assert brand == "UnknownBrand"
        assert model == "Model X"
        
        # Test with single word
        brand, model = scraper._extract_brand_model("SingleWord")
        assert brand == "SingleWord"
        assert model is None
        
        # Test with empty title
        brand, model = scraper._extract_brand_model("")
        assert brand is None
        assert model is None
    
    def test_build_absolute_url(self, mock_base_scraper):
        """Test building absolute URLs."""
        mock_base_scraper.config.base_url = "https://example.com"
        
        # Already absolute URL
        result = mock_base_scraper._build_absolute_url("https://other.com/path")
        assert result == "https://other.com/path"
        
        # Relative URL
        result = mock_base_scraper._build_absolute_url("/watches/rolex")
        assert result == "https://example.com/watches/rolex"
        
        # Empty URL
        result = mock_base_scraper._build_absolute_url("")
        assert result == ""
    
    def test_clean_reference(self, mock_base_scraper):
        """Test reference number cleaning."""
        # With prefix
        result = mock_base_scraper._clean_reference("Ref. 116610LN")
        assert result == "116610LN"
        
        result = mock_base_scraper._clean_reference("Reference: 311.30.42")
        assert result == "311.30.42"
        
        # Without prefix
        result = mock_base_scraper._clean_reference("123456")
        assert result == "123456"
        
        # With special characters
        result = mock_base_scraper._clean_reference("REF#: 123-ABC/456")
        assert result == "123-ABC456"
        
        # Empty reference
        result = mock_base_scraper._clean_reference("")
        assert result is None
        
        result = mock_base_scraper._clean_reference(None)
        assert result is None


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
    async def test_extract_watches_success(self, mock_aiohttp_session, mock_logger):
        """Test successful watch extraction from World of Time."""
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
            image_selector="img",
            known_brands={"rolex": "Rolex", "omega": "Omega"}
        )
        
        html_content = """
        <div class="watch-listings">
            <div class="watch-item">
                <h3 class="title">Rolex Submariner Date</h3>
                <a href="/watches/rolex-submariner">View Details</a>
                <span class="price">€8,500.00</span>
                <img src="/images/submariner.jpg" alt="Rolex">
            </div>
            <div class="watch-item">
                <h3 class="title">Omega Speedmaster</h3>
                <a href="/watches/omega-speedmaster">View Details</a>
                <span class="price">€4,200.00</span>
                <img src="/images/speedmaster.jpg" alt="Omega">
            </div>
        </div>
        """
        
        scraper = WorldOfTimeScraper(config, mock_aiohttp_session, mock_logger)
        soup = BeautifulSoup(html_content, 'html.parser')
        
        result = await scraper._extract_watches(soup)
        
        assert len(result) == 2
        
        # Check first watch
        watch1 = result[0]
        assert watch1.title == "Rolex Submariner Date"
        assert watch1.url == "https://www.worldoftime.de/watches/rolex-submariner"
        assert watch1.price == Decimal("8500.00")
        assert watch1.currency == "EUR"
        assert watch1.brand == "Rolex"
        assert watch1.site_name == "World of Time"
        assert watch1.site_key == "worldoftime"
        assert watch1.image_url == "https://www.worldoftime.de/images/submariner.jpg"
        
        # Check second watch
        watch2 = result[1]
        assert watch2.title == "Omega Speedmaster"
        assert watch2.brand == "Omega"
        assert watch2.price == Decimal("4200.00")
    
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
    async def test_extract_watches_parsing_error(self, mock_aiohttp_session, mock_logger):
        """Test watch extraction with parsing errors."""
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
        
        html_content = """
        <div class="watch-item">
            <h3 class="title">Valid Watch</h3>
            <a href="/valid">Link</a>
            <span class="price">€1,000</span>
        </div>
        <div class="watch-item">
            <!-- This element will cause an error during parsing -->
        </div>
        """
        
        scraper = WorldOfTimeScraper(config, mock_aiohttp_session, mock_logger)
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Mock _parse_watch_element to raise error for second element
        original_parse = scraper._parse_watch_element
        call_count = 0
        
        def mock_parse(element):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise Exception("Parse error")
            return original_parse(element)
        
        scraper._parse_watch_element = mock_parse
        
        result = await scraper._extract_watches(soup)
        
        # Should return only the successfully parsed watch
        assert len(result) == 1
        assert result[0].title == "Valid Watch"
    
    @pytest.mark.asyncio
    async def test_extract_watch_details(self, mock_aiohttp_session, mock_logger):
        """Test extracting watch details from detail page."""
        config = SiteConfig(
            name="World of Time",
            key="worldoftime",
            url="https://www.worldoftime.de/Watches/NewArrivals",
            webhook_env_var="WORLDOFTIME_WEBHOOK_URL",
            color=0x2F4F4F,
            base_url="https://www.worldoftime.de",
            detail_page_selectors={
                "table": "table.details",
                "reference_header": "reference",
                "year_header": "year",
                "condition_header": "condition",
                "material_header": "case material",
                "diameter_header": "diameter"
            }
        )
        
        detail_html = """
        <html>
            <body>
                <table class="details">
                    <tr><th>Reference</th><td>116610LN</td></tr>
                    <tr><th>Year</th><td>2020</td></tr>
                    <tr><th>Condition</th><td>Excellent</td></tr>
                    <tr><th>Case Material</th><td>Steel</td></tr>
                    <tr><th>Diameter</th><td>40mm</td></tr>
                </table>
                <div>Box and papers included</div>
            </body>
        </html>
        """
        
        watch = WatchData(
            title="Rolex Submariner",
            url="https://example.com/watch",
            site_name="World of Time",
            site_key="worldoftime"
        )
        
        scraper = WorldOfTimeScraper(config, mock_aiohttp_session, mock_logger)
        soup = BeautifulSoup(detail_html, 'html.parser')
        
        await scraper._extract_watch_details(watch, soup)
        
        assert watch.reference == "116610LN"
        assert watch.year == "2020"
        assert watch.condition is not None  # Should be parsed
        assert watch.case_material == "Steel"
        assert watch.diameter == "40mm"
        assert watch.has_papers is True
        assert watch.has_box is True
    
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
    
    def test_clean_diameter(self, mock_aiohttp_session, mock_logger):
        """Test diameter value cleaning."""
        config = SiteConfig(
            name="World of Time",
            key="worldoftime", 
            url="https://www.worldoftime.de/Watches/NewArrivals",
            webhook_env_var="WORLDOFTIME_WEBHOOK_URL",
            color=0x2F4F4F,
            base_url="https://www.worldoftime.de"
        )
        
        scraper = WorldOfTimeScraper(config, mock_aiohttp_session, mock_logger)
        
        # Already formatted
        result = scraper._clean_diameter("40mm")
        assert result == "40mm"
        
        # Without mm suffix
        result = scraper._clean_diameter("42")
        assert result == "42mm"
        
        # With extra spaces
        result = scraper._clean_diameter("  38mm  ")
        assert result == "38mm"
        
        # Invalid format
        result = scraper._clean_diameter("Large")
        assert result == "Large"  # Should return as-is if not numeric
        
        # Empty or None
        result = scraper._clean_diameter("")
        assert result is None
        
        result = scraper._clean_diameter(None)
        assert result is None