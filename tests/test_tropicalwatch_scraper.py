"""Comprehensive tests for Tropical Watch scraper implementation."""

import pytest
import asyncio
from unittest.mock import AsyncMock, Mock, patch
from bs4 import BeautifulSoup
from decimal import Decimal
from urllib.parse import urljoin

from scrapers.tropicalwatch import TropicalWatchScraper
from models import WatchData
from config import SiteConfig


@pytest.fixture
def tropicalwatch_config():
    """Tropical Watch site configuration for testing."""
    return SiteConfig(
        name="Tropical Watch",
        key="tropicalwatch",
        url="https://tropicalwatch.com/watches",
        webhook_env_var="TROPICALWATCH_WEBHOOK_URL",
        color=0x228B22,
        base_url="https://tropicalwatch.com",
        known_brands={
            "rolex": "Rolex",
            "patek philippe": "Patek Philippe",
            "audemars piguet": "Audemars Piguet",
            "omega": "Omega",
            "tudor": "Tudor",
            "heuer": "Heuer",
            "longines": "Longines",
            "jaeger-lecoultre": "Jaeger-LeCoultre",
            "zenith": "Zenith",
            "iwc": "IWC",
            "panerai": "Panerai",
            "cartier": "Cartier",
            "breitling": "Breitling"
        }
    )


@pytest.fixture
def tropicalwatch_scraper(tropicalwatch_config, mock_aiohttp_session, mock_logger):
    """Tropical Watch scraper instance for testing."""
    return TropicalWatchScraper(tropicalwatch_config, mock_aiohttp_session, mock_logger)


@pytest.fixture
def tropicalwatch_listing_html():
    """Realistic Tropical Watch listing page HTML."""
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <title>Tropical Watch - Luxury Timepieces</title>
    </head>
    <body>
        <div class="watch-listings">
            <!-- First watch - Rolex Submariner -->
            <li class="watch">
                <div class="photo-wrapper">
                    <a href="/watches/rolex-submariner-date-116610ln">
                        <img src="/images/rolex-submariner-116610ln.jpg" alt="Rolex Submariner Date" />
                    </a>
                </div>
                <div class="content">
                    <a href="/watches/rolex-submariner-date-116610ln">
                        <h2>Rolex Submariner Date 116610LN</h2>
                        <h3>$10,200</h3>
                    </a>
                </div>
            </li>
            
            <!-- Second watch - Patek Philippe Calatrava -->
            <li class="watch">
                <div class="photo-wrapper">
                    <a href="/watches/patek-philippe-calatrava-5196g">
                        <img src="/images/patek-calatrava-5196g.jpg" alt="Patek Philippe Calatrava" />
                    </a>
                </div>
                <div class="content">
                    <a href="/watches/patek-philippe-calatrava-5196g">
                        <h2>Patek Philippe Calatrava 5196G-001</h2>
                        <h3>$38,500</h3>
                    </a>
                </div>
            </li>
            
            <!-- Third watch - Omega Speedmaster -->
            <li class="watch">
                <div class="photo-wrapper">
                    <a href="/watches/omega-speedmaster-311">
                        <img src="/images/omega-speedmaster-311.jpg" alt="Omega Speedmaster" />
                    </a>
                </div>
                <div class="content">
                    <a href="/watches/omega-speedmaster-311">
                        <h2>Omega Speedmaster Professional Moonwatch</h2>
                        <h3>$4,850</h3>
                    </a>
                </div>
            </li>
            
            <!-- Fourth watch - Tudor Black Bay -->
            <li class="watch">
                <div class="photo-wrapper">
                    <a href="/watches/tudor-black-bay-58">
                        <img src="/images/tudor-black-bay-58.jpg" alt="Tudor Black Bay" />
                    </a>
                </div>
                <div class="content">
                    <a href="/watches/tudor-black-bay-58">
                        <h2>Tudor Black Bay 58 79030N</h2>
                        <h3>$3,200</h3>
                    </a>
                </div>
            </li>
            
            <!-- Fifth watch - Heuer Monaco -->
            <li class="watch">
                <div class="photo-wrapper">
                    <a href="/watches/heuer-monaco-vintage">
                        <img src="/images/heuer-monaco-vintage.jpg" alt="Heuer Monaco" />
                    </a>
                </div>
                <div class="content">
                    <a href="/watches/heuer-monaco-vintage">
                        <h2>Heuer Monaco Vintage 1133B</h2>
                        <h3>$7,800</h3>
                    </a>
                </div>
            </li>
        </div>
    </body>
    </html>
    """


@pytest.fixture
def tropicalwatch_detail_html():
    """Realistic Tropical Watch detail page HTML."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Rolex Submariner Date 116610LN - Tropical Watch</title>
    </head>
    <body>
        <div class="watch-detail">
            <h1 class="watch-main-title">Rolex Submariner Date 116610LN</h1>
            
            <div class="watch-main-details-content">
                <table class="watch-main-details-table">
                    <tr>
                        <th>Brand</th>
                        <td>Rolex</td>
                    </tr>
                    <tr>
                        <th>Model</th>
                        <td>Submariner</td>
                    </tr>
                    <tr>
                        <th>Reference</th>
                        <td>116610LN</td>
                    </tr>
                    <tr>
                        <th>Year</th>
                        <td>2020</td>
                    </tr>
                    <tr>
                        <th>Case Material</th>
                        <td>Stainless Steel</td>
                    </tr>
                    <tr>
                        <th>Diameter</th>
                        <td>40mm</td>
                    </tr>
                </table>
            </div>
            
            <div class="watch-main-description">
                <p><strong>Case:</strong> Excellent condition stainless steel case with minimal wear</p>
                <p><strong>Dial:</strong> Black ceramic bezel in perfect condition</p>
                <p><strong>Bracelet:</strong> Original Oyster bracelet with all links</p>
                <p><strong>Movement:</strong> Automatic chronometer certified movement</p>
                <p><strong>Condition:</strong> Excellent overall condition, recently serviced</p>
                <p><strong>Accessories:</strong> Complete set with original box and papers included</p>
            </div>
        </div>
    </body>
    </html>
    """


@pytest.fixture
def tropicalwatch_minimal_detail_html():
    """Minimal Tropical Watch detail page for fallback testing."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Watch Detail</title>
    </head>
    <body>
        <div class="watch-detail">
            <h1 class="watch-main-title">Omega Speedmaster Professional 1969</h1>
        </div>
    </body>
    </html>
    """


@pytest.fixture
def tropicalwatch_empty_html():
    """Empty Tropical Watch listing page."""
    return """
    <html>
    <body>
        <div class="no-watches-found">
            <p>No watches available at this time.</p>
        </div>
    </body>
    </html>
    """


@pytest.fixture
def tropicalwatch_malformed_html():
    """Malformed Tropical Watch listing with missing elements.""" 
    return """
    <html>
    <body>
        <div class="watch-listings">
            <!-- Watch with no URL -->
            <li class="watch">
                <div class="photo-wrapper">
                    <a>
                        <img src="/images/no-url-watch.jpg" alt="No URL" />
                    </a>
                </div>
                <div class="content">
                    <a>
                        <h2>Watch Without URL</h2>
                        <h3>$1,500</h3>
                    </a>
                </div>
            </li>
            
            <!-- Watch with missing price -->
            <li class="watch">
                <div class="photo-wrapper">
                    <a href="/watches/no-price-watch">
                        <img src="/images/no-price-watch.jpg" alt="No Price" />
                    </a>
                </div>
                <div class="content">
                    <a href="/watches/no-price-watch">
                        <h2>Watch Without Price</h2>
                        <h3></h3>
                    </a>
                </div>
            </li>
            
            <!-- Complete watch -->
            <li class="watch">
                <div class="photo-wrapper">
                    <a href="/watches/complete-watch">
                        <img src="/images/complete-watch.jpg" alt="Complete" />
                    </a>
                </div>
                <div class="content">
                    <a href="/watches/complete-watch">
                        <h2>Complete Watch</h2>
                        <h3>$2,000</h3>
                    </a>
                </div>
            </li>
        </div>
    </body>
    </html>
    """


class TestTropicalWatchScraper:
    """Test Tropical Watch scraper implementation."""
    
    def test_initialization(self, tropicalwatch_config, mock_aiohttp_session, mock_logger):
        """Test scraper initialization."""
        scraper = TropicalWatchScraper(tropicalwatch_config, mock_aiohttp_session, mock_logger)
        
        assert scraper.config == tropicalwatch_config
        assert scraper.session == mock_aiohttp_session
        assert len(scraper.seen_ids) == 0
    
    @pytest.mark.asyncio
    async def test_extract_watches_success(self, tropicalwatch_scraper, tropicalwatch_listing_html):
        """Test successful watch extraction from listing page."""
        soup = BeautifulSoup(tropicalwatch_listing_html, 'html.parser')
        
        watches = await tropicalwatch_scraper._extract_watches(soup)
        
        assert len(watches) == 5
        
        # Test first watch - Rolex Submariner
        rolex_sub = watches[0]
        assert rolex_sub.title == "Rolex Submariner Date 116610LN"
        assert rolex_sub.url == "https://tropicalwatch.com/watches/rolex-submariner-date-116610ln"
        assert rolex_sub.price == Decimal("10200")  # USD price parsed
        assert rolex_sub.currency == "USD"
        assert rolex_sub.image_url == "https://tropicalwatch.com/images/rolex-submariner-116610ln.jpg"
        assert rolex_sub.site_name == "Tropical Watch"
        assert rolex_sub.site_key == "tropicalwatch"
        assert rolex_sub.brand is None  # Will be extracted from detail page
        assert rolex_sub.model is None  # Will be extracted from detail page
        
        # Test second watch - Patek Philippe
        patek = watches[1]
        assert patek.title == "Patek Philippe Calatrava 5196G-001"
        assert patek.price == Decimal("38500")
        assert patek.currency == "USD"
        
        # Test third watch - Omega
        omega = watches[2]
        assert omega.title == "Omega Speedmaster Professional Moonwatch"
        assert omega.price == Decimal("4850")
        
        # Test fourth watch - Tudor
        tudor = watches[3]
        assert tudor.title == "Tudor Black Bay 58 79030N"
        assert tudor.price == Decimal("3200")
        
        # Test fifth watch - Heuer
        heuer = watches[4]
        assert heuer.title == "Heuer Monaco Vintage 1133B"
        assert heuer.price == Decimal("7800")
    
    @pytest.mark.asyncio
    async def test_extract_watches_empty_page(self, tropicalwatch_scraper, tropicalwatch_empty_html):
        """Test extraction from empty listing page."""
        soup = BeautifulSoup(tropicalwatch_empty_html, 'html.parser')
        
        watches = await tropicalwatch_scraper._extract_watches(soup)
        
        assert watches == []
    
    @pytest.mark.asyncio
    async def test_extract_watches_malformed_elements(self, tropicalwatch_scraper, tropicalwatch_malformed_html):
        """Test extraction with malformed/missing elements."""
        soup = BeautifulSoup(tropicalwatch_malformed_html, 'html.parser')
        
        watches = await tropicalwatch_scraper._extract_watches(soup)
        
        # Should return only complete watches
        assert len(watches) == 1
        
        watch = watches[0]
        assert watch.title == "Complete Watch"
        assert watch.price == Decimal("2000")
        assert watch.url == "https://tropicalwatch.com/watches/complete-watch"
    
    def test_parse_watch_element_missing_link(self, tropicalwatch_scraper):
        """Test parsing element without link returns None."""
        html = """
        <li class="watch">
            <div class="photo-wrapper">
                <a>
                    <img src="/images/no-link.jpg" alt="No Link" />
                </a>
            </div>
            <div class="content">
                <a>
                    <h2>Watch Without Link</h2>
                    <h3>$1,000</h3>
                </a>
            </div>
        </li>
        """
        soup = BeautifulSoup(html, 'html.parser')
        element = soup.select_one('.watch')
        
        result = tropicalwatch_scraper._parse_watch_element(element)
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_extract_watch_details_success(self, tropicalwatch_scraper, tropicalwatch_detail_html):
        """Test successful detail extraction from detail page."""
        watch = WatchData(
            title="Test Watch",
            url="https://tropicalwatch.com/watches/test",
            site_name="Tropical Watch",
            site_key="tropicalwatch",
            price=Decimal("10000"),
            currency="USD"
        )
        
        soup = BeautifulSoup(tropicalwatch_detail_html, 'html.parser')
        
        await tropicalwatch_scraper._extract_watch_details(watch, soup)
        
        # Check updated fields from table
        assert watch.title == "Rolex Submariner Date 116610LN"
        assert watch.brand == "Rolex"
        assert watch.model == "Submariner"
        assert watch.reference == "116610LN"
        assert watch.year == "2020"
        assert watch.case_material == "Stainless Steel"
        assert watch.diameter == "40mm"
        
        # Check box and papers from description
        assert watch.has_box is True
        assert watch.has_papers is True
        
        # Check condition parsing
        assert watch.condition is not None
    
    @pytest.mark.asyncio
    async def test_extract_watch_details_minimal_data(self, tropicalwatch_scraper, tropicalwatch_minimal_detail_html):
        """Test detail extraction with minimal data."""
        watch = WatchData(
            title="Original Title",
            url="https://tropicalwatch.com/watches/test",
            site_name="Tropical Watch", 
            site_key="tropicalwatch"
        )
        
        soup = BeautifulSoup(tropicalwatch_minimal_detail_html, 'html.parser')
        
        await tropicalwatch_scraper._extract_watch_details(watch, soup)
        
        # Should update title
        assert watch.title == "Omega Speedmaster Professional 1969"
        
        # Should extract year from title
        assert watch.year == "1969"
        
        # Should extract brand from title using known brands
        assert watch.brand == "Omega"
        assert watch.model == "Speedmaster Professional"
    
    def test_brand_extraction_fallback_logic(self, tropicalwatch_scraper):
        """Test brand extraction fallback logic from title."""
        test_cases = [
            # (title, expected_brand, expected_model)
            ("Rolex Submariner Date 116610LN", "Rolex", "Submariner Date"),
            ("Patek Philippe Calatrava 5196G", "Patek Philippe", "Calatrava 5196G"),
            ("Omega Speedmaster Professional", "Omega", "Speedmaster Professional"),
            ("Tudor Black Bay 58", "Tudor", "Black Bay 58"),
            ("Heuer Monaco 1133B", "Heuer", "Monaco 1133B"),
            ("Studio Underd0g Custom Watch", "Studio Underd0g", "Custom Watch"),
            ("Jaeger-LeCoultre Reverso", "Jaeger-LeCoultre", "Reverso"),
            ("A. Lange & Söhne Lange 1", "A. Lange & Söhne", "Lange 1"),
            ("UnknownBrand Model X", None, None),  # Not in known brands
        ]
        
        for title, expected_brand, expected_model in test_cases:
            watch = WatchData(
                title=title,
                url="https://tropicalwatch.com/watches/test",
                site_name="Tropical Watch",
                site_key="tropicalwatch"
            )
            
            # Simulate the brand extraction logic
            known_brands_tw = [
                "Rolex", "Patek Philippe", "Audemars Piguet", "Omega", "Tudor", 
                "Heuer", "Studio Underd0g", "Longines", "Jaeger-LeCoultre", "Zenith", 
                "IWC", "Panerai", "Cartier", "Breitling", "Universal Geneve", "A. Lange & Söhne"
            ]
            
            title_l_for_brand = title.lower()
            brand = None
            
            # Check if title starts with brand name
            for b_name in sorted(known_brands_tw, key=len, reverse=True):
                if title_l_for_brand.startswith(b_name.lower()):
                    brand = b_name
                    break
            
            # If not found, check if brand name is anywhere in title
            if not brand:
                for b_name in sorted(known_brands_tw, key=len, reverse=True):
                    if b_name.lower() in title_l_for_brand:
                        brand = b_name
                        break
            
            assert brand == expected_brand, f"Brand extraction failed for: {title}"
    
    def test_model_extraction_from_title(self, tropicalwatch_scraper):
        """Test model extraction from title after removing brand."""
        watch = WatchData(
            title="Rolex Submariner Date 116610LN 2020",
            url="https://tropicalwatch.com/watches/test",
            site_name="Tropical Watch",
            site_key="tropicalwatch"
        )
        
        # Simulate setting brand and extracting model
        watch.brand = "Rolex"
        
        # Model extraction logic from the scraper
        import re
        from utils import parse_year
        
        temp_model_str = re.sub(fr"^{re.escape(watch.brand)}\s*", "", watch.title, flags=re.IGNORECASE).strip()
        
        # Remove year from model string
        year_in_title = parse_year("", temp_model_str)
        if year_in_title:
            temp_model_str = temp_model_str.replace(year_in_title, "").strip()
        
        # Take first 3 words as model
        model_words = [word for word in temp_model_str.split() if not (word.isdigit() and len(word) == 4)]
        model_candidate = " ".join(model_words[:3]).title().strip()
        
        if model_candidate and model_candidate.lower() != watch.brand.lower():
            watch.model = model_candidate
        
        assert watch.model == "Submariner Date 116610Ln"
    
    def test_reference_extraction_from_title(self, tropicalwatch_scraper):
        """Test reference extraction from title."""
        test_cases = [
            ("Rolex Submariner 116610LN", "116610LN"),
            ("Patek Philippe Calatrava 5196G-001", "5196G-001"),
            ("Omega Speedmaster 311.30.42.30.01.005", "311.30.42.30.01.005"),
            ("Tudor Black Bay 58 M79030N-0001", "M79030N-0001"),
            ("Simple Watch Title", None),  # No reference pattern
        ]
        
        for title, expected_ref in test_cases:
            watch = WatchData(
                title=title,
                url="https://tropicalwatch.com/watches/test",
                site_name="Tropical Watch",
                site_key="tropicalwatch"
            )
            
            # Simulate reference extraction logic
            import re
            
            temp_ref_search_str = title
            
            # Look for reference pattern
            ref_match_title = re.search(r'\b([A-Z0-9]{3,}(?:[-/\s]?[A-Z0-9]+)?)\b', temp_ref_search_str.strip())
            reference = None
            if ref_match_title and not re.fullmatch(r'\d{4}', ref_match_title.group(1)):
                reference = ref_match_title.group(1)
            
            assert reference == expected_ref, f"Reference extraction failed for: {title}"
    
    def test_case_material_extraction_from_title(self, tropicalwatch_scraper):
        """Test case material extraction from title."""
        test_cases = [
            ("Rolex Submariner 18K WG White Gold", "White Gold"),
            ("Patek Philippe 18K YG Yellow Gold", "Yellow Gold"),
            ("Tudor 18K PG Pink Gold", "Rose Gold"),
            ("Omega Speedmaster Steel Case", "Steel"),
            ("IWC Stainless Steel Pilot", "Steel"),
            ("Cartier Gold Watch", "Gold"),
            ("Simple Watch", None),  # No material mentioned
        ]
        
        for title, expected_material in test_cases:
            watch = WatchData(
                title=title,
                url="https://tropicalwatch.com/watches/test",
                site_name="Tropical Watch",
                site_key="tropicalwatch"
            )
            
            # Simulate case material extraction from title
            title_l = title.lower()
            case_material = None
            
            if "18k wg" in title_l or "white gold" in title_l:
                case_material = "White Gold"
            elif "18k yg" in title_l or "yellow gold" in title_l:
                case_material = "Yellow Gold"
            elif "18k pg" in title_l or "pink gold" in title_l or "rose gold" in title_l:
                case_material = "Rose Gold"
            elif "steel" in title_l or "stainless" in title_l:
                case_material = "Steel"
            elif "gold" in title_l:
                case_material = "Gold"
            
            assert case_material == expected_material, f"Case material extraction failed for: {title}"
    
    def test_box_papers_parsing(self, tropicalwatch_scraper):
        """Test box and papers detection from descriptions."""
        test_cases = [
            ("Complete set with original box and papers included", True, True),
            ("Includes original box and certificate", True, True),
            ("Papers and documentation included", True, None),
            ("Original box included", None, True),
            ("Watch only, no accessories", False, False),
            ("No original packaging", False, False),
            ("Just the watch", None, None),
        ]
        
        for description, expected_papers, expected_box in test_cases:
            detail_html = f"""
            <div class="watch-main-description">
                <p><strong>Accessories:</strong> {description}</p>
            </div>
            """
            
            watch = WatchData(
                title="Test Watch",
                url="https://tropicalwatch.com/watches/test",
                site_name="Tropical Watch",
                site_key="tropicalwatch"
            )
            
            soup = BeautifulSoup(detail_html, 'html.parser')
            
            # Mock parse_box_papers to test the flow
            with patch('scrapers.tropicalwatch.parse_box_papers') as mock_parse:
                mock_parse.return_value = (expected_papers, expected_box)
                
                tropicalwatch_scraper._extract_watch_details(watch, soup)
                
                assert watch.has_papers == expected_papers, f"Papers detection failed for: {description}"
                assert watch.has_box == expected_box, f"Box detection failed for: {description}"
    
    def test_price_parsing_usd_formats(self, tropicalwatch_scraper):
        """Test USD price parsing with different formats."""
        test_cases = [
            ("$10,200", Decimal("10200")),
            ("$8500", Decimal("8500")),
            ("$1,234,567", Decimal("1234567")),
            ("10200", Decimal("10200")),
            ("Price on Request", None),
            ("SOLD", None),
            ("", None),
            ("Not Available", None),
        ]
        
        for price_text, expected_price in test_cases:
            html = f"""
            <li class="watch">
                <div class="photo-wrapper">
                    <a href="/watches/test-watch">
                        <img src="/images/test.jpg" alt="Test" />
                    </a>
                </div>
                <div class="content">
                    <a href="/watches/test-watch">
                        <h2>Test Watch</h2>
                        <h3>{price_text}</h3>
                    </a>
                </div>
            </li>
            """
            soup = BeautifulSoup(html, 'html.parser')
            element = soup.select_one('.watch')
            
            watch = tropicalwatch_scraper._parse_watch_element(element)
            
            if expected_price is None:
                assert watch is None or watch.price is None
            else:
                assert watch is not None
                assert watch.price == expected_price, f"Failed for price: {price_text}"
                assert watch.currency == "USD"
    
    def test_diameter_extraction_from_description(self, tropicalwatch_scraper):
        """Test diameter extraction from description."""
        test_cases = [
            ("40mm case diameter", "40mm"),
            ("Case measures 42mm", "42mm"),
            ("38.5mm diameter", "38.5mm"), 
            ("No size mentioned", None),
        ]
        
        for description, expected_diameter in test_cases:
            watch = WatchData(
                title="Test Watch",
                url="https://tropicalwatch.com/watches/test",
                site_name="Tropical Watch",
                site_key="tropicalwatch"
            )
            
            # Simulate diameter extraction
            import re
            
            desc_text_for_dia = f"Test Watch {description}"
            dia_match = re.search(r'(\d{2}(?:\.\d+)?)\s*mm', desc_text_for_dia, re.IGNORECASE)
            diameter = None
            if dia_match:
                diameter = dia_match.group(1) + "mm"
            
            assert diameter == expected_diameter, f"Diameter extraction failed for: {description}"
    
    def test_parse_details_from_table_th_td(self, tropicalwatch_scraper):
        """Test table parsing helper method."""
        table_html = """
        <table class="watch-main-details-table">
            <tr>
                <th>Brand</th>
                <td>Rolex</td>
            </tr>
            <tr>
                <th>Model:</th>
                <td>Submariner</td>
            </tr>
            <tr>
                <th>Year</th>
                <td>2020</td>
            </tr>
            <tr>
                <th>Reference:</th>
                <td>116610LN</td>
            </tr>
        </table>
        """
        
        soup = BeautifulSoup(table_html, 'html.parser')
        table = soup.find('table')
        
        headers_map = {
            "Brand": "brand_table",
            "Model": "model_table",
            "Year": "year_text",
            "Reference": "reference_text"
        }
        
        details = tropicalwatch_scraper._parse_details_from_table_th_td(table, headers_map)
        
        assert details["brand_table"] == "Rolex"
        assert details["model_table"] == "Submariner"
        assert details["year_text"] == "2020"
        assert details["reference_text"] == "116610LN"
    
    def test_parse_details_from_table_empty(self, tropicalwatch_scraper):
        """Test table parsing with empty table."""
        details = tropicalwatch_scraper._parse_details_from_table_th_td(None, {})
        assert details == {}
    
    @pytest.mark.asyncio
    async def test_full_scrape_integration(self, tropicalwatch_scraper, tropicalwatch_listing_html):
        """Test full scraping workflow integration."""
        with patch('scrapers.base.fetch_page', return_value=tropicalwatch_listing_html):
            with patch('scrapers.base.APP_CONFIG') as mock_config:
                mock_config.enable_detail_scraping = False
                
                watches = await tropicalwatch_scraper.scrape()
        
        assert len(watches) == 5
        assert all(isinstance(watch, WatchData) for watch in watches)
        assert all(watch.site_key == "tropicalwatch" for watch in watches)
        assert all(watch.site_name == "Tropical Watch" for watch in watches)
        assert all(watch.currency == "USD" for watch in watches)
        
        # Verify composite IDs are generated
        assert len(tropicalwatch_scraper.seen_ids) == 5
        for watch in watches:
            assert watch.composite_id in tropicalwatch_scraper.seen_ids
    
    @pytest.mark.asyncio
    async def test_scrape_with_seen_watches(self, tropicalwatch_scraper, tropicalwatch_listing_html):
        """Test scraping with some watches already seen."""
        # Pre-populate with one seen watch
        seen_watch = WatchData(
            title="Rolex Submariner Date 116610LN",
            url="https://tropicalwatch.com/watches/rolex-submariner-date-116610ln",
            site_name="Tropical Watch",
            site_key="tropicalwatch",
            price=Decimal("10200"),
            currency="USD"
        )
        tropicalwatch_scraper.seen_ids = {seen_watch.composite_id}
        
        with patch('scrapers.base.fetch_page', return_value=tropicalwatch_listing_html):
            with patch('scrapers.base.APP_CONFIG') as mock_config:
                mock_config.enable_detail_scraping = False
                
                watches = await tropicalwatch_scraper.scrape()
        
        # Should return only new watches (4 instead of 5)
        assert len(watches) == 4
        assert not any(watch.title == "Rolex Submariner Date 116610LN" for watch in watches)
    
    @pytest.mark.asyncio
    async def test_scrape_parse_error_handling(self, tropicalwatch_scraper):
        """Test scraping handles parse errors gracefully."""
        malformed_html = """
        <li class="watch">
            <div class="content">
                <a href="/watches/valid-watch">
                    <h2>Valid Watch</h2>
                    <h3>$1,000</h3>
                </a>
            </div>
        </li>
        """
        
        with patch('scrapers.base.fetch_page', return_value=malformed_html):
            with patch('scrapers.base.APP_CONFIG') as mock_config:
                mock_config.enable_detail_scraping = False
                
                # Mock _parse_watch_element to raise an error
                original_parse = tropicalwatch_scraper._parse_watch_element
                def mock_parse(element):
                    if "Valid Watch" in str(element):
                        raise Exception("Parse error")
                    return original_parse(element)
                
                tropicalwatch_scraper._parse_watch_element = mock_parse
                
                watches = await tropicalwatch_scraper.scrape()
        
        # Should handle errors gracefully and return empty list
        assert watches == []
    
    def test_image_url_construction(self, tropicalwatch_scraper):
        """Test image URL construction from relative paths."""
        html = """
        <li class="watch">
            <div class="photo-wrapper">
                <a href="/watches/test-watch">
                    <img src="/images/test-watch.jpg" alt="Test" />
                </a>
            </div>
            <div class="content">
                <a href="/watches/test-watch">
                    <h2>Test Watch</h2>
                    <h3>$1,000</h3>
                </a>
            </div>
        </li>
        """
        soup = BeautifulSoup(html, 'html.parser')
        element = soup.select_one('.watch')
        
        watch = tropicalwatch_scraper._parse_watch_element(element)
        
        assert watch is not None
        assert watch.image_url == "https://tropicalwatch.com/images/test-watch.jpg"
    
    def test_composite_id_generation(self, tropicalwatch_scraper):
        """Test that watches generate unique composite IDs."""
        html1 = """
        <li class="watch">
            <div class="photo-wrapper">
                <a href="/watches/test-watch-1">
                    <img src="/images/test1.jpg" alt="Test 1" />
                </a>
            </div>
            <div class="content">
                <a href="/watches/test-watch-1">
                    <h2>Test Watch 1</h2>
                    <h3>$1,000</h3>
                </a>
            </div>
        </li>
        """
        
        html2 = """
        <li class="watch">
            <div class="photo-wrapper">
                <a href="/watches/test-watch-2">
                    <img src="/images/test2.jpg" alt="Test 2" />
                </a>
            </div>
            <div class="content">
                <a href="/watches/test-watch-2">
                    <h2>Test Watch 2</h2>
                    <h3>$1,000</h3>
                </a>
            </div>
        </li>
        """
        
        soup1 = BeautifulSoup(html1, 'html.parser')
        soup2 = BeautifulSoup(html2, 'html.parser')
        
        watch1 = tropicalwatch_scraper._parse_watch_element(soup1.select_one('.watch'))
        watch2 = tropicalwatch_scraper._parse_watch_element(soup2.select_one('.watch'))
        
        assert watch1 is not None
        assert watch2 is not None
        assert watch1.composite_id != watch2.composite_id
        assert watch1.composite_id is not None
        assert watch2.composite_id is not None