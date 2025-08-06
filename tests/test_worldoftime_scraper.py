"""Comprehensive tests for WorldOfTime scraper implementation."""

import pytest
import asyncio
from unittest.mock import AsyncMock, Mock, patch
from bs4 import BeautifulSoup
from decimal import Decimal
from urllib.parse import urljoin

from scrapers.worldoftime import WorldOfTimeScraper
from models import WatchData
from config import SiteConfig


@pytest.fixture
def worldoftime_config():
    """WorldOfTime site configuration for testing."""
    return SiteConfig(
        name="World of Time",
        key="worldoftime",
        url="https://www.worldoftime.de/Watches/NewArrivals",
        webhook_env_var="WORLDOFTIME_WEBHOOK_URL",
        color=0x2F4F4F,
        base_url="https://www.worldoftime.de",
        known_brands={
            "patek philippe": "Patek Philippe",
            "rolex vintage": "Rolex",
            "rolex": "Rolex",
            "omega": "Omega",
            "iwc": "IWC",
            "jaeger lecoultre": "Jaeger LeCoultre",
            "cartier": "Cartier",
            "breitling": "Breitling",
            "audemars piguet": "Audemars Piguet",
            "heuer": "Heuer",
            "universal geneve": "Universal Genève",
            "panerai": "Panerai",
            "tudor": "Tudor",
            "longines": "Longines",
            "zenith": "Zenith",
            "a. lange & söhne": "A. Lange & Söhne"
        }
    )


@pytest.fixture
def worldoftime_scraper(worldoftime_config, mock_aiohttp_session, mock_logger):
    """WorldOfTime scraper instance for testing."""
    return WorldOfTimeScraper(worldoftime_config, mock_aiohttp_session, mock_logger)


@pytest.fixture
def worldoftime_listing_html():
    """Realistic WorldOfTime listing page HTML."""
    return """
    <!DOCTYPE html>
    <html lang="de">
    <head>
        <title>World of Time - New Arrivals</title>
    </head>
    <body>
        <div class="new-arrivals-container">
            <!-- First watch - Rolex Submariner -->
            <div class="new-arrivals-watch">
                <div class="image">
                    <a href="/Watches/Rolex/Submariner-Date-116610LN">
                        <img src="/images/submariner-116610ln.jpg" alt="Rolex Submariner" />
                    </a>
                </div>
                <div class="text-truncate" style="font-size: 17px; font-family: 'AB';">
                    Rolex Submariner Date 
                </div>
                <div class="text-truncate" style="font-size: 16px; color: #666;">
                    Ref. 116610LN
                </div>
                <div class="pt-4 mt-auto">
                    <p class="m-0 price" style="font-size: 17px;">€8.500,00</p>
                </div>
                <p class="m-0 truncate-two-lines">
                    Black dial, ceramic bezel, year 2020, excellent condition with box and papers, steel case
                </p>
            </div>
            
            <!-- Second watch - Omega Speedmaster -->
            <div class="new-arrivals-watch">
                <div class="image">
                    <a href="/Watches/Omega/Speedmaster-Professional">
                        <img src="/images/speedmaster-prof.jpg" alt="Omega Speedmaster" />
                    </a>
                </div>
                <div class="text-truncate" style="font-size: 17px; font-family: 'AB';">
                    Omega Speedmaster Professional Moonwatch
                </div>
                <div class="text-truncate" style="font-size: 16px; color: #666;">
                    Ref. 311.30.42.30.01.005
                </div>
                <div class="pt-4 mt-auto">
                    <p class="m-0 price" style="font-size: 17px;">€4.200,00</p>
                </div>
                <p class="m-0 truncate-two-lines">
                    Manual wind chronograph, year 2019, very good condition, titanium case
                </p>
            </div>
            
            <!-- Third watch - Patek Philippe with vintage keyword -->
            <div class="new-arrivals-watch">
                <div class="image">
                    <a href="/Watches/Patek-Philippe/Calatrava-5196G">
                        <img src="/images/patek-calatrava.jpg" alt="Patek Philippe" />
                    </a>
                </div>
                <div class="text-truncate" style="font-size: 17px; font-family: 'AB';">
                    Patek Philippe Calatrava
                </div>
                <div class="text-truncate" style="font-size: 16px; color: #666;">
                    Ref. 5196G-001
                </div>
                <div class="pt-4 mt-auto">
                    <p class="m-0 price" style="font-size: 17px;">€32.000,00</p>
                </div>
                <p class="m-0 truncate-two-lines">
                    White gold case, year 2018, mint condition, gold movement
                </p>
            </div>
            
            <!-- Fourth watch - Rolex Vintage -->
            <div class="new-arrivals-watch">
                <div class="image">
                    <a href="/Watches/Rolex/Vintage-GMT-Master">
                        <img src="/images/rolex-vintage-gmt.jpg" alt="Rolex Vintage" />
                    </a>
                </div>
                <div class="text-truncate" style="font-size: 17px; font-family: 'AB';">
                    Rolex Vintage GMT-Master
                </div>
                <div class="text-truncate" style="font-size: 16px; color: #666;">
                    Ref. 1675
                </div>
                <div class="pt-4 mt-auto">
                    <p class="m-0 price" style="font-size: 17px;">€15.800,00</p>
                </div>
                <p class="m-0 truncate-two-lines">
                    Vintage 1970s, pepsi bezel, original condition with papers only
                </p>
            </div>
            
            <!-- Fifth watch - Unknown brand -->
            <div class="new-arrivals-watch">
                <div class="image">
                    <a href="/Watches/Misc/Unknown-Brand-Watch">
                        <img src="/images/unknown-watch.jpg" alt="Unknown Watch" />
                    </a>
                </div>
                <div class="text-truncate" style="font-size: 17px; font-family: 'AB';">
                    UnknownBrand Model X Special Edition
                </div>
                <div class="text-truncate" style="font-size: 16px; color: #666;">
                    Ref. UBX-2023
                </div>
                <div class="pt-4 mt-auto">
                    <p class="m-0 price" style="font-size: 17px;">€1.200,00</p>
                </div>
                <p class="m-0 truncate-two-lines">
                    Modern watch, year 2023, new condition
                </p>
            </div>
        </div>
        
        <!-- Alternative layout for paged results -->
        <div class="paged-clocks-container">
            <div class="watch-link">
                <div class="image">
                    <a href="/Watches/IWC/Pilot-Mark-XVIII">
                        <img class="square-container" src="/images/iwc-pilot.jpg" alt="IWC Pilot" />
                    </a>
                </div>
                <div class="text-truncate" style="font-size: 17px; font-family: 'AB';">
                    IWC Pilot's Watch Mark XVIII
                </div>
                <div class="text-truncate" style="font-size: 16px; color: #666;">
                    Ref. IW327001
                </div>
                <p class="m-0 price" style="font-size: 17px;">€3.800,00</p>
                <p class="m-0 characteristics">
                    Automatic movement, year 2021, excellent condition with box, steel case
                </p>
            </div>
        </div>
    </body>
    </html>
    """


@pytest.fixture
def worldoftime_empty_html():
    """Empty WorldOfTime listing page."""
    return """
    <html>
    <body>
        <div class="no-watches-found">
            <p>No new arrivals at this time.</p>
        </div>
    </body>
    </html>
    """


@pytest.fixture
def worldoftime_malformed_html():
    """Malformed WorldOfTime listing with missing elements."""
    return """
    <html>
    <body>
        <div class="new-arrivals-watch">
            <!-- Missing title -->
            <div class="image">
                <a href="/Watches/Incomplete/Watch1">
                    <img src="/images/incomplete1.jpg" alt="Incomplete" />
                </a>
            </div>
            <div class="pt-4 mt-auto">
                <p class="m-0 price" style="font-size: 17px;">€1.000,00</p>
            </div>
        </div>
        
        <div class="new-arrivals-watch">
            <!-- Missing link -->
            <div class="text-truncate" style="font-size: 17px; font-family: 'AB';">
                Watch Without Link
            </div>
            <div class="pt-4 mt-auto">
                <p class="m-0 price" style="font-size: 17px;">€2.000,00</p>
            </div>
        </div>
        
        <div class="new-arrivals-watch">
            <!-- Missing price -->
            <div class="image">
                <a href="/Watches/Incomplete/Watch3">
                    <img src="/images/incomplete3.jpg" alt="No Price" />
                </a>
            </div>
            <div class="text-truncate" style="font-size: 17px; font-family: 'AB';">
                Watch Without Price
            </div>
        </div>
    </body>
    </html>
    """


class TestWorldOfTimeScraper:
    """Test WorldOfTime scraper implementation."""
    
    def test_initialization(self, worldoftime_config, mock_aiohttp_session, mock_logger):
        """Test scraper initialization."""
        scraper = WorldOfTimeScraper(worldoftime_config, mock_aiohttp_session, mock_logger)
        
        assert scraper.config == worldoftime_config
        assert scraper.session == mock_aiohttp_session
        assert len(scraper.seen_ids) == 0
    
    @pytest.mark.asyncio
    async def test_extract_watches_success(self, worldoftime_scraper, worldoftime_listing_html):
        """Test successful watch extraction from listing page."""
        soup = BeautifulSoup(worldoftime_listing_html, 'html.parser')
        
        watches = await worldoftime_scraper._extract_watches(soup)
        
        assert len(watches) == 6  # 5 from new-arrivals + 1 from paged-clocks
        
        # Test first watch - Rolex Submariner
        rolex_sub = watches[0]
        assert rolex_sub.title == "Rolex Submariner Date"
        assert rolex_sub.brand == "Rolex"
        assert rolex_sub.model == "Submariner Date"
        assert rolex_sub.reference == "116610LN"
        assert rolex_sub.price == Decimal("8500.00")
        assert rolex_sub.currency == "EUR"
        assert rolex_sub.year == "2020"
        assert rolex_sub.case_material == "Steel"
        assert rolex_sub.has_box is True
        assert rolex_sub.has_papers is True
        assert rolex_sub.condition is not None
        assert rolex_sub.url == "https://www.worldoftime.de/Watches/Rolex/Submariner-Date-116610LN"
        assert rolex_sub.image_url == "https://www.worldoftime.de/images/submariner-116610ln.jpg"
        assert rolex_sub.site_name == "World of Time"
        assert rolex_sub.site_key == "worldoftime"
        
        # Test second watch - Omega Speedmaster
        omega_speedy = watches[1]
        assert omega_speedy.title == "Omega Speedmaster Professional Moonwatch"
        assert omega_speedy.brand == "Omega"
        assert omega_speedy.model == "Speedmaster Professional Moonwatch"
        assert omega_speedy.reference == "311.30.42.30.01.005"
        assert omega_speedy.price == Decimal("4200.00")
        assert omega_speedy.year == "2019"
        assert omega_speedy.case_material == "Titanium"
        assert omega_speedy.has_papers is None  # Not mentioned in description
        assert omega_speedy.has_box is None
        
        # Test third watch - Patek Philippe
        patek = watches[2]
        assert patek.title == "Patek Philippe Calatrava"
        assert patek.brand == "Patek Philippe"
        assert patek.model == "Calatrava"
        assert patek.reference == "5196G-001"
        assert patek.price == Decimal("32000.00")
        assert patek.year == "2018"
        assert patek.case_material == "Gold"  # Should map "gold" to "Gold"
        
        # Test fourth watch - Rolex Vintage
        rolex_vintage = watches[3]
        assert rolex_vintage.title == "Rolex Vintage GMT-Master"
        assert rolex_vintage.brand == "Rolex"
        assert rolex_vintage.model == "Vintage GMT-Master"
        assert rolex_vintage.reference == "1675"
        assert rolex_vintage.price == Decimal("15800.00")
        assert rolex_vintage.has_papers is True
        assert rolex_vintage.has_box is None  # Only papers mentioned
        
        # Test fifth watch - Unknown brand
        unknown = watches[4]
        assert unknown.title == "UnknownBrand Model X Special Edition"
        assert unknown.brand == "UnknownBrand"
        assert unknown.model == "Model X Special Edition"
        assert unknown.reference == "UBX-2023"
        assert unknown.price == Decimal("1200.00")
        assert unknown.year == "2023"
        
        # Test sixth watch - IWC from paged container
        iwc = watches[5]
        assert iwc.title == "IWC Pilot's Watch Mark XVIII"
        assert iwc.brand == "IWC"
        assert iwc.model == "Pilot's Watch Mark XVIII"
        assert iwc.reference == "IW327001"
        assert iwc.price == Decimal("3800.00")
        assert iwc.year == "2021"
        assert iwc.case_material == "Steel"
        assert iwc.has_box is True
        assert iwc.has_papers is None
    
    @pytest.mark.asyncio
    async def test_extract_watches_empty_page(self, worldoftime_scraper, worldoftime_empty_html):
        """Test extraction from empty listing page."""
        soup = BeautifulSoup(worldoftime_empty_html, 'html.parser')
        
        watches = await worldoftime_scraper._extract_watches(soup)
        
        assert watches == []
    
    @pytest.mark.asyncio
    async def test_extract_watches_malformed_elements(self, worldoftime_scraper, worldoftime_malformed_html):
        """Test extraction with malformed/missing elements."""
        soup = BeautifulSoup(worldoftime_malformed_html, 'html.parser')
        
        watches = await worldoftime_scraper._extract_watches(soup)
        
        # Should return only the watch with complete data
        assert len(watches) == 1
        
        watch = watches[0]
        assert watch.title == "Watch Without Price"
        assert watch.price is None  # Missing price
        assert watch.url == "https://www.worldoftime.de/Watches/Incomplete/Watch3"
    
    def test_parse_watch_element_missing_link(self, worldoftime_scraper):
        """Test parsing element without link returns None."""
        html = """
        <div class="new-arrivals-watch">
            <div class="text-truncate" style="font-size: 17px; font-family: 'AB';">
                Watch Without Link
            </div>
        </div>
        """
        soup = BeautifulSoup(html, 'html.parser')
        element = soup.select_one('.new-arrivals-watch')
        
        result = worldoftime_scraper._parse_watch_element(element)
        
        assert result is None
    
    def test_brand_model_extraction_known_brands(self, worldoftime_scraper):
        """Test brand and model extraction for known brands."""
        test_cases = [
            ("Rolex Submariner Date", "Rolex", "Submariner Date"),
            ("Patek Philippe Calatrava 5196G", "Patek Philippe", "Calatrava 5196G"),
            ("Omega Speedmaster Professional", "Omega", "Speedmaster Professional"),
            ("A. Lange & Söhne Lange 1", "A. Lange & Söhne", "Lange 1"),
            ("Jaeger LeCoultre Reverso", "Jaeger LeCoultre", "Reverso"),
            ("Universal Genève Polerouter", "Universal Genève", "Polerouter"),
        ]
        
        for title, expected_brand, expected_model in test_cases:
            # Create mock element
            element = Mock()
            element.select_one.return_value = None
            
            # Mock the title extraction
            with patch('scrapers.worldoftime.extract_text_from_element') as mock_extract:
                mock_extract.return_value = title
                
                html = f"""
                <div class="new-arrivals-watch">
                    <div class="image">
                        <a href="/test">Test</a>
                    </div>
                    <div class="text-truncate" style="font-size: 17px; font-family: 'AB';">
                        {title}
                    </div>
                </div>
                """
                soup = BeautifulSoup(html, 'html.parser')
                element = soup.select_one('.new-arrivals-watch')
                
                watch = worldoftime_scraper._parse_watch_element(element)
                
                assert watch is not None
                assert watch.brand == expected_brand
                assert watch.model == expected_model
    
    def test_brand_model_extraction_rolex_vintage(self, worldoftime_scraper):
        """Test special handling of Rolex Vintage."""
        html = """
        <div class="new-arrivals-watch">
            <div class="image">
                <a href="/test">Test</a>
            </div>
            <div class="text-truncate" style="font-size: 17px; font-family: 'AB';">
                Rolex Vintage GMT-Master
            </div>
        </div>
        """
        soup = BeautifulSoup(html, 'html.parser')
        element = soup.select_one('.new-arrivals-watch')
        
        watch = worldoftime_scraper._parse_watch_element(element)
        
        assert watch is not None
        assert watch.brand == "Rolex"
        assert watch.model == "Vintage GMT-Master"
    
    def test_case_material_extraction(self, worldoftime_scraper):
        """Test case material extraction from descriptions."""
        test_cases = [
            ("steel case", "Steel"),
            ("edelstahl case", "Steel"),
            ("yellow-gold bracelet", "Yellow Gold"),
            ("gelbgold case", "Yellow Gold"),
            ("white-gold bezel", "White Gold"),
            ("weissgold material", "White Gold"),
            ("rose gold case", "Rose Gold"),
            ("rosegold finish", "Rose Gold"),
            ("titanium case", "Titanium"),
            ("platinum material", "Platinum"),
            ("ceramic bezel", "Ceramic"),
            ("nickel plated case", "Nickel"),
            ("gold case", "Gold"),  # Generic gold
        ]
        
        for description, expected_material in test_cases:
            html = f"""
            <div class="new-arrivals-watch">
                <div class="image">
                    <a href="/test">Test</a>
                </div>
                <div class="text-truncate" style="font-size: 17px; font-family: 'AB';">
                    Test Watch
                </div>
                <p class="m-0 truncate-two-lines">
                    {description}
                </p>
            </div>
            """
            soup = BeautifulSoup(html, 'html.parser')
            element = soup.select_one('.new-arrivals-watch')
            
            watch = worldoftime_scraper._parse_watch_element(element)
            
            assert watch is not None
            assert watch.case_material == expected_material, f"Failed for: {description}"
    
    def test_box_papers_parsing(self, worldoftime_scraper):
        """Test box and papers detection from descriptions."""
        test_cases = [
            ("with box and papers", True, True),
            ("box and papers included", True, True),
            ("papers only", True, None),
            ("with papers", True, None),
            ("box only", None, True),
            ("with original box", None, True),
            ("no box or papers", False, False),
            ("without papers", False, None),
            ("no mention", None, None),
        ]
        
        for description, expected_papers, expected_box in test_cases:
            html = f"""
            <div class="new-arrivals-watch">
                <div class="image">
                    <a href="/test">Test</a>
                </div>
                <div class="text-truncate" style="font-size: 17px; font-family: 'AB';">
                    Test Watch
                </div>
                <p class="m-0 truncate-two-lines">
                    {description}
                </p>
            </div>
            """
            soup = BeautifulSoup(html, 'html.parser')
            element = soup.select_one('.new-arrivals-watch')
            
            watch = worldoftime_scraper._parse_watch_element(element)
            
            assert watch is not None
            assert watch.has_papers == expected_papers, f"Papers failed for: {description}"
            assert watch.has_box == expected_box, f"Box failed for: {description}"
    
    def test_price_parsing_various_formats(self, worldoftime_scraper):
        """Test price parsing with different formats."""
        test_cases = [
            ("€8.500,00", Decimal("8500.00")),
            ("€1.234,56", Decimal("1234.56")),
            ("€999", Decimal("999.00")),
            ("8500 EUR", Decimal("8500.00")),
            ("8.500", Decimal("8500.00")),
            ("Price on request", None),
            ("", None),
            ("Invalid price", None),
        ]
        
        for price_text, expected_price in test_cases:
            html = f"""
            <div class="new-arrivals-watch">
                <div class="image">
                    <a href="/test">Test</a>
                </div>
                <div class="text-truncate" style="font-size: 17px; font-family: 'AB';">
                    Test Watch
                </div>
                <div class="pt-4 mt-auto">
                    <p class="m-0 price" style="font-size: 17px;">{price_text}</p>
                </div>
            </div>
            """
            soup = BeautifulSoup(html, 'html.parser')
            element = soup.select_one('.new-arrivals-watch')
            
            watch = worldoftime_scraper._parse_watch_element(element)
            
            assert watch is not None
            assert watch.price == expected_price, f"Failed for price: {price_text}"
    
    def test_reference_extraction_with_wot_id_filter(self, worldoftime_scraper):
        """Test reference extraction filters out WoT-ID."""
        html = """
        <div class="new-arrivals-watch">
            <div class="image">
                <a href="/test">Test</a>
            </div>
            <div class="text-truncate" style="font-size: 17px; font-family: 'AB';">
                Test Watch
            </div>
            <div class="text-truncate" style="font-size: 16px; color: #666;">
                Ref. 116610LN | Wot-ID: 12345
            </div>
        </div>
        """
        soup = BeautifulSoup(html, 'html.parser')
        element = soup.select_one('.new-arrivals-watch')
        
        watch = worldoftime_scraper._parse_watch_element(element)
        
        assert watch is not None
        assert watch.reference is None  # Should be filtered out due to Wot-ID
    
    def test_year_extraction_from_description(self, worldoftime_scraper):
        """Test year extraction from watch descriptions."""
        test_cases = [
            ("year 2020", "2020"),
            ("from 2019", "2019"),
            ("manufactured in 2021", "2021"),
            ("vintage 1970s", "1970"),
            ("circa 1980", "1980"),
            ("no year mentioned", None),
        ]
        
        for description, expected_year in test_cases:
            html = f"""
            <div class="new-arrivals-watch">
                <div class="image">
                    <a href="/test">Test</a>
                </div>
                <div class="text-truncate" style="font-size: 17px; font-family: 'AB';">
                    Test Watch
                </div>
                <p class="m-0 truncate-two-lines">
                    {description}
                </p>
            </div>
            """
            soup = BeautifulSoup(html, 'html.parser')
            element = soup.select_one('.new-arrivals-watch')
            
            watch = worldoftime_scraper._parse_watch_element(element)
            
            assert watch is not None
            assert watch.year == expected_year, f"Failed for description: {description}"
    
    @pytest.mark.asyncio
    async def test_extract_watch_details_no_implementation(self, worldoftime_scraper):
        """Test that detail extraction is not implemented for WorldOfTime."""
        watch = WatchData(
            title="Test Watch",
            url="https://example.com/test",
            site_name="World of Time",
            site_key="worldoftime"
        )
        
        soup = BeautifulSoup("<html></html>", 'html.parser')
        
        # Should not raise any errors and not modify the watch
        original_title = watch.title
        await worldoftime_scraper._extract_watch_details(watch, soup)
        
        assert watch.title == original_title
    
    @pytest.mark.asyncio
    async def test_full_scrape_integration(self, worldoftime_scraper, worldoftime_listing_html):
        """Test full scraping workflow integration."""
        with patch('scrapers.base.fetch_page', return_value=worldoftime_listing_html):
            with patch('scrapers.base.APP_CONFIG') as mock_config:
                mock_config.enable_detail_scraping = False
                
                watches = await worldoftime_scraper.scrape()
        
        assert len(watches) == 6
        assert all(isinstance(watch, WatchData) for watch in watches)
        assert all(watch.site_key == "worldoftime" for watch in watches)
        assert all(watch.site_name == "World of Time" for watch in watches)
        
        # Verify composite IDs are generated
        assert len(worldoftime_scraper.seen_ids) == 6
        for watch in watches:
            assert watch.composite_id in worldoftime_scraper.seen_ids
    
    @pytest.mark.asyncio
    async def test_scrape_with_seen_watches(self, worldoftime_scraper, worldoftime_listing_html):
        """Test scraping with some watches already seen."""
        # Pre-populate with one seen watch
        seen_watch = WatchData(
            title="Rolex Submariner Date",
            url="https://www.worldoftime.de/Watches/Rolex/Submariner-Date-116610LN",
            site_name="World of Time",
            site_key="worldoftime",
            price=Decimal("8500.00"),
            currency="EUR"
        )
        worldoftime_scraper.seen_ids = {seen_watch.composite_id}
        
        with patch('scrapers.base.fetch_page', return_value=worldoftime_listing_html):
            with patch('scrapers.base.APP_CONFIG') as mock_config:
                mock_config.enable_detail_scraping = False
                
                watches = await worldoftime_scraper.scrape()
        
        # Should return only new watches (5 instead of 6)
        assert len(watches) == 5
        assert not any(watch.title == "Rolex Submariner Date" for watch in watches)
    
    @pytest.mark.asyncio
    async def test_scrape_parse_error_handling(self, worldoftime_scraper):
        """Test scraping handles parse errors gracefully."""
        # Create HTML that will cause parsing errors
        malformed_html = """
        <div class="new-arrivals-watch">
            <div class="text-truncate" style="font-size: 17px; font-family: 'AB';">
                Valid Watch
            </div>
            <div class="image">
                <a href="/valid">Link</a>
            </div>
        </div>
        """
        
        with patch('scrapers.base.fetch_page', return_value=malformed_html):
            with patch('scrapers.base.APP_CONFIG') as mock_config:
                mock_config.enable_detail_scraping = False
                
                # Mock _parse_watch_element to raise an error for some elements
                original_parse = worldoftime_scraper._parse_watch_element
                def mock_parse(element):
                    if "Valid Watch" in str(element):
                        raise Exception("Parse error")
                    return original_parse(element)
                
                worldoftime_scraper._parse_watch_element = mock_parse
                
                watches = await worldoftime_scraper.scrape()
        
        # Should handle errors gracefully and return empty list
        assert watches == []
    
    def test_image_url_construction(self, worldoftime_scraper):
        """Test image URL construction from relative paths."""
        html = """
        <div class="new-arrivals-watch">
            <div class="image">
                <a href="/test">
                    <img src="/images/test-watch.jpg" alt="Test" />
                </a>
            </div>
            <div class="text-truncate" style="font-size: 17px; font-family: 'AB';">
                Test Watch
            </div>
        </div>
        """
        soup = BeautifulSoup(html, 'html.parser')
        element = soup.select_one('.new-arrivals-watch')
        
        watch = worldoftime_scraper._parse_watch_element(element)
        
        assert watch is not None
        assert watch.image_url == "https://www.worldoftime.de/images/test-watch.jpg"
    
    def test_composite_id_generation(self, worldoftime_scraper):
        """Test that watches generate unique composite IDs."""
        html = """
        <div class="new-arrivals-watch">
            <div class="image">
                <a href="/test-watch-1">Test</a>  
            </div>
            <div class="text-truncate" style="font-size: 17px; font-family: 'AB';">
                Test Watch 1
            </div>
            <div class="pt-4 mt-auto">
                <p class="m-0 price" style="font-size: 17px;">€1.000,00</p>
            </div>
        </div>
        """
        soup = BeautifulSoup(html, 'html.parser')
        element = soup.select_one('.new-arrivals-watch')
        
        watch1 = worldoftime_scraper._parse_watch_element(element)
        
        # Modify URL to create different watch
        html2 = html.replace("/test-watch-1", "/test-watch-2").replace("Test Watch 1", "Test Watch 2")
        soup2 = BeautifulSoup(html2, 'html.parser')
        element2 = soup2.select_one('.new-arrivals-watch')
        
        watch2 = worldoftime_scraper._parse_watch_element(element2)
        
        assert watch1 is not None
        assert watch2 is not None
        assert watch1.composite_id != watch2.composite_id
        assert watch1.composite_id is not None
        assert watch2.composite_id is not None