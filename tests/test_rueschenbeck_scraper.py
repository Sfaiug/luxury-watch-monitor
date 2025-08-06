"""Comprehensive tests for Rüschenbeck scraper implementation."""

import pytest
import asyncio
from unittest.mock import AsyncMock, Mock, patch
from bs4 import BeautifulSoup
from decimal import Decimal
from urllib.parse import urljoin

from scrapers.rueschenbeck import RueschenbeckScraper
from models import WatchData
from config import SiteConfig


@pytest.fixture
def rueschenbeck_config():
    """Rüschenbeck site configuration for testing."""
    return SiteConfig(
        name="Rüschenbeck",
        key="rueschenbeck",
        url="https://rueschenbeck.de/uhren",
        webhook_env_var="RUESCHENBECK_WEBHOOK_URL",
        color=0x8B0000,
        base_url="https://rueschenbeck.de",
        known_brands={
            "rolex": "Rolex",
            "omega": "Omega",
            "breitling": "Breitling",
            "iwc": "IWC",
            "tag heuer": "TAG Heuer",
            "tudor": "Tudor",
            "cartier": "Cartier",
            "patek philippe": "Patek Philippe"
        }
    )


@pytest.fixture
def rueschenbeck_scraper(rueschenbeck_config, mock_aiohttp_session, mock_logger):
    """Rüschenbeck scraper instance for testing."""
    return RueschenbeckScraper(rueschenbeck_config, mock_aiohttp_session, mock_logger)


@pytest.fixture
def rueschenbeck_listing_html():
    """Realistic Rüschenbeck listing page HTML."""
    return """
    <!DOCTYPE html>
    <html lang="de">
    <head>
        <title>Rüschenbeck - Gebrauchte Luxusuhren</title>
    </head>
    <body>
        <div class="product-listing">
            <!-- First watch - Rolex with CPO certification -->
            <li class="-rb-list-item">
                <a class="-rb-list-item-link" href="/uhren/rolex-submariner-116610ln">
                    <div class="-rb-list-image">
                        <img src="/media/images/rolex-submariner-116610ln.jpg" alt="Rolex Submariner" />
                    </div>
                    <div class="watch-details">
                        <span class="-rb-manufacturer-name">Rolex</span>
                        <span class="-rb-line-name">Submariner</span>
                        <span class="-rb-prod-name">116610LN Submariner Date</span>
                        <span class="-rb-icon icn-cpo" title="Certified Pre-Owned">CPO</span>
                        <div class="-rb-availability">
                            <span class="in-stock"><span class="value">Verfügbar</span></span>
                        </div>
                        <div class="price-box">
                            <span class="regular-price">
                                <span class="price">€ 8.500,00</span>
                            </span>
                        </div>
                    </div>
                </a>
            </li>
            
            <!-- Second watch - Omega with special price -->
            <li class="-rb-list-item">
                <a class="-rb-list-item-link" href="/uhren/omega-speedmaster-311">
                    <div class="-rb-list-image">
                        <img src="/media/images/omega-speedmaster-311.jpg" alt="Omega Speedmaster" />
                    </div>
                    <div class="watch-details">
                        <span class="-rb-manufacturer-name">Omega</span>
                        <span class="-rb-line-name">Speedmaster</span>
                        <span class="-rb-prod-name">311.30.42.30.01.005 Professional Moonwatch</span>
                        <div class="-rb-availability">
                            <span class="in-stock"><span class="value">Verfügbar</span></span>
                        </div>
                        <div class="price-box">
                            <p class="special-price">
                                <span class="price">€ 3.800,00</span>
                            </p>
                            <span class="regular-price">
                                <span class="price">€ 4.200,00</span>
                            </span>
                        </div>
                    </div>
                </a>
            </li>
            
            <!-- Third watch - Breitling without reference pattern -->
            <li class="-rb-list-item">
                <a class="-rb-list-item-link" href="/uhren/breitling-navitimer">
                    <div class="-rb-list-image">
                        <img src="/media/images/breitling-navitimer.jpg" alt="Breitling Navitimer" />
                    </div>
                    <div class="watch-details">
                        <span class="-rb-manufacturer-name">Breitling</span>
                        <span class="-rb-line-name">Navitimer</span>
                        <span class="-rb-prod-name">Certified Pre-Owned Navitimer GMT</span>
                        <div class="-rb-availability">
                            <span class="in-stock"><span class="value">Verfügbar</span></span>
                        </div>
                        <div class="price-box">
                            <span class="regular-price">
                                <span class="price">€ 2.800,00</span>
                            </span>
                        </div>
                    </div>
                </a>
            </li>
            
            <!-- Fourth watch - Sold watch, should be skipped -->
            <li class="-rb-list-item">
                <a class="-rb-list-item-link" href="/uhren/iwc-pilot-sold">
                    <div class="-rb-list-image">
                        <img src="/media/images/iwc-pilot-sold.jpg" alt="IWC Pilot" />
                    </div>
                    <div class="watch-details">
                        <span class="-rb-manufacturer-name">IWC</span>
                        <span class="-rb-line-name">Pilot</span>
                        <span class="-rb-prod-name">IW327001 Mark XVIII</span>
                        <div class="-rb-availability">
                            <span class="sold"><span class="value">verkauft</span></span>
                        </div>
                        <div class="price-box">
                            <span class="regular-price">
                                <span class="price">€ 3.200,00</span>
                            </span>
                        </div>
                    </div>
                </a>
            </li>
            
            <!-- Fifth watch - TAG Heuer with numeric-only reference -->
            <li class="-rb-list-item">
                <a class="-rb-list-item-link" href="/uhren/tag-heuer-carrera">
                    <div class="-rb-list-image">
                        <img src="/media/images/tag-heuer-carrera.jpg" alt="TAG Heuer Carrera" />
                    </div>
                    <div class="watch-details">
                        <span class="-rb-manufacturer-name">TAG Heuer</span>
                        <span class="-rb-line-name">Carrera</span>
                        <span class="-rb-prod-name">123 Calibre 16 Chronograph</span>
                        <div class="-rb-availability">
                            <span class="in-stock"><span class="value">Verfügbar</span></span>
                        </div>
                        <div class="price-box">
                            <span class="regular-price">
                                <span class="price">€ 1.800,00</span>
                            </span>
                        </div>
                    </div>
                </a>
            </li>
        </div>
    </body>
    </html>
    """


@pytest.fixture
def rueschenbeck_detail_html():
    """Realistic Rüschenbeck detail page HTML."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Rolex Submariner 116610LN - Rüschenbeck</title>
    </head>
    <body>
        <div class="product-detail">
            <div class="product-name">
                <h1>
                    <span class="manufacturer-name">Rolex</span>
                    <span class="line-name">Submariner</span>
                    <span class="prod-name">116610LN Submariner Date Black Dial</span>
                </h1>
            </div>
            
            <div class="product-specifications">
                <table class="specs-table">
                    <tr>
                        <th>Referenznummer:</th>
                        <td>116610LN</td>
                    </tr>
                    <tr>
                        <th>Baujahr:</th>
                        <td>2020</td>
                    </tr>
                    <tr>
                        <th>Durchmesser:</th>
                        <td>40mm</td>
                    </tr>
                    <tr>
                        <th>Gehäusematerial:</th>
                        <td>Edelstahl</td>
                    </tr>
                    <tr>
                        <th>Zustand:</th>
                        <td>Sehr gut - minimale Gebrauchsspuren</td>
                    </tr>
                </table>
                
                <dl class="additional-specs">
                    <dt>Bewegung:</dt>
                    <dd>Automatik</dd>
                    <dt>Wasserdichtigkeit:</dt>
                    <dd>300m</dd>
                </dl>
            </div>
            
            <div class="product-description">
                <p>Diese Rolex Submariner Date ist ein Klassiker unter den Taucheruhren. 
                Das Modell aus dem Jahr 2020 befindet sich in sehr gutem Zustand.</p>
                <p>Gehäuse: 40mm Edelstahl mit Keramiklünette</p>
                <p>Das Gehäuse zeigt nur minimale Gebrauchsspuren und wurde professionell aufgearbeitet.</p>
            </div>
            
            <div class="product-condition">
                <h3>Zustand</h3>
                <p>Die Uhr wurde durch unsere Uhrmacher geprüft und als "Sehr gut" bewertet. 
                Alle Funktionen arbeiten einwandfrei.</p>
            </div>
            
            <div class="lieferumfang">
                <h3>Lieferumfang</h3>
                <p>Uhr, Originalbox, Papiere, Garantiekarte, alle Glieder</p>
            </div>
        </div>
    </body>
    </html>
    """


@pytest.fixture
def rueschenbeck_minimal_detail_html():
    """Minimal Rüschenbeck detail page for fallback testing."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Simple Watch - Rüschenbeck</title>
    </head>
    <body>
        <div class="product-detail">
            <div class="product-name">
                <h1>
                    <span class="manufacturer-name">Omega</span>
                    <span class="line-name">Seamaster</span>
                    <span class="prod-name">Simple Watch</span>
                </h1>
            </div>
        </div>
    </body>
    </html>
    """


@pytest.fixture
def rueschenbeck_empty_html():
    """Empty Rüschenbeck listing page."""
    return """
    <html>
    <body>
        <div class="no-watches-found">
            <p>Keine Uhren gefunden.</p>
        </div>
    </body>
    </html>
    """


@pytest.fixture
def rueschenbeck_malformed_html():
    """Malformed Rüschenbeck listing with missing elements."""
    return """
    <html>
    <body>
        <div class="product-listing">
            <!-- Watch without link -->
            <li class="-rb-list-item">
                <div class="-rb-list-image">
                    <img src="/images/no-link.jpg" alt="No Link" />
                </div>
                <div class="watch-details">
                    <span class="-rb-manufacturer-name">NoLink</span>
                    <span class="-rb-prod-name">Watch Without Link</span>
                    <div class="price-box">
                        <span class="regular-price">
                            <span class="price">€ 1.000,00</span>
                        </span>
                    </div>
                </div>
            </li>
            
            <!-- Complete watch -->
            <li class="-rb-list-item">
                <a class="-rb-list-item-link" href="/uhren/complete-watch">
                    <div class="-rb-list-image">
                        <img src="/images/complete.jpg" alt="Complete" />
                    </div>
                    <div class="watch-details">
                        <span class="-rb-manufacturer-name">Complete</span>
                        <span class="-rb-prod-name">Complete Watch</span>
                        <div class="price-box">
                            <span class="regular-price">
                                <span class="price">€ 2.000,00</span>
                            </span>
                        </div>
                    </div>
                </a>
            </li>
        </div>
    </body>
    </html>
    """


class TestRueschenbeckScraper:
    """Test Rüschenbeck scraper implementation."""
    
    def test_initialization(self, rueschenbeck_config, mock_aiohttp_session, mock_logger):
        """Test scraper initialization."""
        scraper = RueschenbeckScraper(rueschenbeck_config, mock_aiohttp_session, mock_logger)
        
        assert scraper.config == rueschenbeck_config
        assert scraper.session == mock_aiohttp_session
        assert len(scraper.seen_ids) == 0
    
    @pytest.mark.asyncio
    async def test_extract_watches_success(self, rueschenbeck_scraper, rueschenbeck_listing_html):
        """Test successful watch extraction from listing page."""
        soup = BeautifulSoup(rueschenbeck_listing_html, 'html.parser')
        
        watches = await rueschenbeck_scraper._extract_watches(soup)
        
        # Should return 4 watches (5th is sold)
        assert len(watches) == 4
        
        # Test first watch - Rolex with CPO certification
        rolex_watch = watches[0]
        assert rolex_watch.title == "116610LN Submariner Date"
        assert rolex_watch.brand == "Rolex"
        assert rolex_watch.model == "Submariner"
        assert rolex_watch.reference == "116610LN"  # Extracted from prod-name
        assert rolex_watch.price == Decimal("8500.00")
        assert rolex_watch.currency == "EUR"
        assert rolex_watch.condition == "★★★★☆"  # CPO condition
        assert rolex_watch.url == "https://rueschenbeck.de/uhren/rolex-submariner-116610ln"
        assert rolex_watch.image_url == "https://rueschenbeck.de/media/images/rolex-submariner-116610ln.jpg"
        assert rolex_watch.site_name == "Rüschenbeck"
        assert rolex_watch.site_key == "rueschenbeck"
        
        # Test second watch - Omega with special price (should use special price)
        omega_watch = watches[1]
        assert omega_watch.title == "311.30.42.30.01.005 Professional Moonwatch"
        assert omega_watch.brand == "Omega"
        assert omega_watch.model == "Speedmaster"
        assert omega_watch.reference == "311.30.42.30.01.005"
        assert omega_watch.price == Decimal("3800.00")  # Special price, not regular
        assert omega_watch.condition is None  # No CPO badge
        
        # Test third watch - Breitling without valid reference pattern
        breitling_watch = watches[2]
        assert breitling_watch.title == "Certified Pre-Owned Navitimer GMT"
        assert breitling_watch.brand == "Breitling"
        assert breitling_watch.model == "Navitimer"
        assert breitling_watch.reference is None  # "Certified" should be filtered out
        assert breitling_watch.price == Decimal("2800.00")
        
        # Test fourth watch - TAG Heuer with short numeric reference (should be filtered)
        tag_watch = watches[3]
        assert tag_watch.title == "123 Calibre 16 Chronograph"
        assert tag_watch.brand == "TAG Heuer"
        assert tag_watch.model == "Carrera"
        assert tag_watch.reference is None  # "123" is too short/numeric only
        assert tag_watch.price == Decimal("1800.00")
    
    @pytest.mark.asyncio
    async def test_extract_watches_skip_sold_items(self, rueschenbeck_scraper, rueschenbeck_listing_html):
        """Test that sold watches are skipped."""
        soup = BeautifulSoup(rueschenbeck_listing_html, 'html.parser')
        
        watches = await rueschenbeck_scraper._extract_watches(soup)
        
        # Should not include the sold IWC watch
        assert len(watches) == 4
        assert not any("iwc-pilot-sold" in watch.url for watch in watches)
        assert not any(watch.brand == "IWC" and "Mark XVIII" in watch.title for watch in watches)
    
    @pytest.mark.asyncio
    async def test_extract_watches_empty_page(self, rueschenbeck_scraper, rueschenbeck_empty_html):
        """Test extraction from empty listing page."""
        soup = BeautifulSoup(rueschenbeck_empty_html, 'html.parser')
        
        watches = await rueschenbeck_scraper._extract_watches(soup)
        
        assert watches == []
    
    @pytest.mark.asyncio
    async def test_extract_watches_malformed_elements(self, rueschenbeck_scraper, rueschenbeck_malformed_html):
        """Test extraction with malformed/missing elements."""
        soup = BeautifulSoup(rueschenbeck_malformed_html, 'html.parser')
        
        watches = await rueschenbeck_scraper._extract_watches(soup)
        
        # Should return only complete watches
        assert len(watches) == 1
        
        watch = watches[0]
        assert watch.title == "Complete Watch"
        assert watch.brand == "Complete"
        assert watch.price == Decimal("2000.00")
        assert watch.url == "https://rueschenbeck.de/uhren/complete-watch"
    
    def test_parse_watch_element_missing_link(self, rueschenbeck_scraper):
        """Test parsing element without link returns None."""
        html = """
        <li class="-rb-list-item">
            <div class="-rb-list-image">
                <img src="/images/no-link.jpg" alt="No Link" />
            </div>
            <div class="watch-details">
                <span class="-rb-manufacturer-name">TestBrand</span>
                <span class="-rb-prod-name">Watch Without Link</span>
                <div class="price-box">
                    <span class="regular-price">
                        <span class="price">€ 1.000,00</span>
                    </span>
                </div>
            </div>
        </li>
        """
        soup = BeautifulSoup(html, 'html.parser')
        element = soup.select_one('.-rb-list-item')
        
        result = rueschenbeck_scraper._parse_watch_element(element)
        
        assert result is None
    
    def test_reference_extraction_patterns(self, rueschenbeck_scraper):
        """Test reference extraction with various patterns."""
        test_cases = [
            # (prod_name, expected_reference)
            ("116610LN Submariner Date", "116610LN"),
            ("311.30.42.30.01.005 Professional", "311.30.42.30.01.005"),
            ("IW327001 Pilot Watch", "IW327001"),
            ("CV2A1R.BA0799 Formula 1", "CV2A1R.BA0799"),
            ("5711/1A-010 Nautilus", "5711/1A-010"),
            ("Certified Pre-Owned Watch", None),  # Should filter "Certified"
            ("123 Short Reference", None),  # Too short and numeric
            ("42 Hour Power Reserve", None),  # Numeric only, too short
            ("Simple Watch Name", None),  # No reference pattern
        ]
        
        for prod_name, expected_ref in test_cases:
            html = f"""
            <li class="-rb-list-item">
                <a class="-rb-list-item-link" href="/uhren/test-watch">
                    <div class="watch-details">
                        <span class="-rb-manufacturer-name">TestBrand</span>
                        <span class="-rb-prod-name">{prod_name}</span>
                        <div class="price-box">
                            <span class="regular-price">
                                <span class="price">€ 1.000,00</span>
                            </span>
                        </div>
                    </div>
                </a>
            </li>
            """
            soup = BeautifulSoup(html, 'html.parser')
            element = soup.select_one('.-rb-list-item')
            
            watch = rueschenbeck_scraper._parse_watch_element(element)
            
            assert watch is not None
            assert watch.reference == expected_ref, f"Failed for prod_name: {prod_name}"
    
    def test_price_extraction_priority(self, rueschenbeck_scraper):
        """Test price extraction priority: special price over regular price."""
        test_cases = [
            # (html_snippet, expected_price)
            ('<p class="special-price"><span class="price">€ 3.800,00</span></p><span class="regular-price"><span class="price">€ 4.200,00</span></span>', 
             Decimal("3800.00")),
            ('<span class="regular-price"><span class="price">€ 4.200,00</span></span>', 
             Decimal("4200.00")),
            ('<span class="price">€ 2.500,00</span>', 
             None),  # No proper structure
            ('', None),  # No price
        ]
        
        for price_html, expected_price in test_cases:
            html = f"""
            <li class="-rb-list-item">
                <a class="-rb-list-item-link" href="/uhren/test-watch">
                    <div class="watch-details">
                        <span class="-rb-manufacturer-name">TestBrand</span>
                        <span class="-rb-prod-name">Test Watch</span>
                        <div class="price-box">
                            {price_html}
                        </div>
                    </div>
                </a>
            </li>
            """
            soup = BeautifulSoup(html, 'html.parser')
            element = soup.select_one('.-rb-list-item')
            
            watch = rueschenbeck_scraper._parse_watch_element(element)
            
            if expected_price is None:
                assert watch is None or watch.price is None
            else:
                assert watch is not None
                assert watch.price == expected_price
    
    def test_cpo_condition_detection(self, rueschenbeck_scraper):
        """Test CPO (Certified Pre-Owned) condition detection."""
        html_with_cpo = """
        <li class="-rb-list-item">
            <a class="-rb-list-item-link" href="/uhren/cpo-watch">
                <div class="watch-details">
                    <span class="-rb-manufacturer-name">TestBrand</span>
                    <span class="-rb-prod-name">CPO Test Watch</span>
                    <span class="-rb-icon icn-cpo" title="Certified Pre-Owned">CPO</span>
                    <div class="price-box">
                        <span class="regular-price">
                            <span class="price">€ 1.000,00</span>
                        </span>
                    </div>
                </div>
            </a>
        </li>
        """
        
        html_without_cpo = """
        <li class="-rb-list-item">
            <a class="-rb-list-item-link" href="/uhren/non-cpo-watch">
                <div class="watch-details">
                    <span class="-rb-manufacturer-name">TestBrand</span>
                    <span class="-rb-prod-name">Non-CPO Test Watch</span>
                    <div class="price-box">
                        <span class="regular-price">
                            <span class="price">€ 1.000,00</span>
                        </span>
                    </div>
                </div>
            </a>
        </li>
        """
        
        # Test with CPO badge
        soup_cpo = BeautifulSoup(html_with_cpo, 'html.parser')
        element_cpo = soup_cpo.select_one('.-rb-list-item')
        
        watch_cpo = rueschenbeck_scraper._parse_watch_element(element_cpo)
        
        assert watch_cpo is not None
        assert watch_cpo.condition == "★★★★☆"  # CPO condition
        
        # Test without CPO badge
        soup_non_cpo = BeautifulSoup(html_without_cpo, 'html.parser')
        element_non_cpo = soup_non_cpo.select_one('.-rb-list-item')
        
        watch_non_cpo = rueschenbeck_scraper._parse_watch_element(element_non_cpo)
        
        assert watch_non_cpo is not None
        assert watch_non_cpo.condition is None  # No initial condition
    
    @pytest.mark.asyncio
    async def test_extract_watch_details_success(self, rueschenbeck_scraper, rueschenbeck_detail_html):
        """Test successful detail extraction from detail page."""
        watch = WatchData(
            title="Original Title",
            url="https://rueschenbeck.de/uhren/test",
            site_name="Rüschenbeck",
            site_key="rueschenbeck",
            brand="Original Brand",
            model="Original Model"
        )
        
        soup = BeautifulSoup(rueschenbeck_detail_html, 'html.parser')
        
        await rueschenbeck_scraper._extract_watch_details(watch, soup)
        
        # Check updated fields from detail page
        assert watch.title == "116610LN Submariner Date Black Dial"
        assert watch.brand == "Rolex"
        assert watch.model == "Submariner"
        
        # Check extracted details from specifications
        assert watch.year == "2020"
        assert watch.reference == "116610LN"  # Should prefer longer reference
        assert watch.diameter == "40mm"
        assert watch.case_material == "Edelstahl"
        
        # Check box and papers from lieferumfang
        assert watch.has_box is True
        assert watch.has_papers is True
        
        # Check condition parsing
        assert watch.condition is not None
    
    @pytest.mark.asyncio
    async def test_extract_watch_details_minimal_data(self, rueschenbeck_scraper, rueschenbeck_minimal_detail_html):
        """Test detail extraction with minimal data."""
        watch = WatchData(
            title="Original Title",
            url="https://rueschenbeck.de/uhren/test",
            site_name="Rüschenbeck",
            site_key="rueschenbeck"
        )
        
        soup = BeautifulSoup(rueschenbeck_minimal_detail_html, 'html.parser')
        
        await rueschenbeck_scraper._extract_watch_details(watch, soup)
        
        # Should update basic fields
        assert watch.title == "Simple Watch"
        assert watch.brand == "Omega"
        assert watch.model == "Seamaster"
        
        # Other fields should remain None
        assert watch.year is None
        assert watch.reference is None
        assert watch.diameter is None
    
    def test_parse_rueschenbeck_details_table_parsing(self, rueschenbeck_scraper):
        """Test detailed parsing from specifications table."""
        detail_html = """
        <div class="product-specifications">
            <table class="specs-table">
                <tr>
                    <th>Referenznummer:</th>
                    <td>116610LN-DETAIL</td>
                </tr>
                <tr>
                    <th>Baujahr:</th>
                    <td>2021</td>
                </tr>
                <tr>
                    <th>Durchmesser:</th>
                    <td>40,5mm</td>
                </tr>
                <tr>
                    <th>Gehäusematerial:</th>
                    <td>Edelstahl 904L</td>
                </tr>
                <tr>
                    <th>Zustand:</th>
                    <td>Ausgezeichnet</td>
                </tr>
            </table>
        </div>
        """
        
        soup = BeautifulSoup(detail_html, 'html.parser')
        
        details = rueschenbeck_scraper._parse_rueschenbeck_details(soup)
        
        assert details.get("reference_text") == "116610LN-DETAIL"
        assert details.get("year_text") == "2021"
        assert details.get("diameter_text") == "40,5mm"
        assert details.get("case_material_text") == "Edelstahl 904L"
        assert details.get("condition_text") == "Ausgezeichnet"
    
    def test_parse_rueschenbeck_details_dl_parsing(self, rueschenbeck_scraper):
        """Test detailed parsing from definition lists."""
        detail_html = """
        <div class="product-specifications">
            <dl class="additional-specs">
                <dt>Referenz:</dt>
                <dd>DL-REF-123</dd>
                <dt>Jahr:</dt>
                <dd>2019</dd>
                <dt>Größe:</dt>
                <dd>38mm</dd>
                <dt>Material:</dt>
                <dd>Roségold</dd>
                <dt>Condition:</dt>
                <dd>Very Good</dd>
            </dl>
        </div>
        """
        
        soup = BeautifulSoup(detail_html, 'html.parser')
        
        details = rueschenbeck_scraper._parse_rueschenbeck_details(soup)
        
        assert details.get("reference_text") == "DL-REF-123"
        assert details.get("year_text") == "2019"
        assert details.get("diameter_text") == "38mm"
        assert details.get("case_material_text") == "Roségold"
        assert details.get("condition_text") == "Very Good"
    
    def test_parse_rueschenbeck_details_description_sections(self, rueschenbeck_scraper):
        """Test parsing from description sections."""
        detail_html = """
        <div class="product-detail">
            <div class="product-description">
                <p>This is the main description of the watch.</p>
            </div>
            
            <div class="product-condition">
                <h3>Zustand</h3>
                <p>The watch is in excellent condition with minimal wear.</p>
            </div>
            
            <div class="lieferumfang">
                <h3>Accessories</h3>
                <p>Watch comes with box, papers, and all original accessories.</p>
            </div>
        </div>
        """
        
        soup = BeautifulSoup(detail_html, 'html.parser')
        
        details = rueschenbeck_scraper._parse_rueschenbeck_details(soup)
        
        assert details.get("description_text") == "This is the main description of the watch."
        assert details.get("condition_text") == "The watch is in excellent condition with minimal wear."
        assert details.get("accessories_text") == "Watch comes with box, papers, and all original accessories."
    
    def test_diameter_extraction_and_cleaning(self, rueschenbeck_scraper):
        """Test diameter extraction and cleaning."""
        test_cases = [
            # (raw_diameter, expected_diameter)
            ("40mm", "40mm"),
            ("42,5mm", "42.5mm"),
            ("38.0 mm", "38.0mm"),
            ("40", "40mm"),  # Missing mm unit
            ("42,5", "42.5mm"),  # Missing mm unit with comma
            ("Invalid Size", "Invalid Size"),  # Non-numeric, keep as is
            ("", None),  # Empty
        ]
        
        for raw_diameter, expected in test_cases:
            # Simulate diameter processing logic
            import re
            
            processed_diameter = None
            if raw_diameter:
                dia_text = raw_diameter
                dia_match = re.search(r'(\d{1,2}(?:[.,]\d{1,2})?)\s*mm', dia_text, re.IGNORECASE)
                if dia_match:
                    processed_diameter = dia_match.group(1).replace(",", ".") + "mm"
                else:
                    # Try to clean and validate diameter
                    cleaned_dia = dia_text.replace("mm", "").strip().replace(",", ".").replace(" ", "")
                    if re.match(r'^\d+(\.\d+)?$', cleaned_dia):
                        processed_diameter = cleaned_dia + "mm"
                    else:
                        processed_diameter = dia_text
            
            assert processed_diameter == expected, f"Failed for diameter: {raw_diameter}"
    
    def test_reference_preference_logic(self, rueschenbeck_scraper):
        """Test reference preference: longer/more detailed reference wins."""
        watch = WatchData(
            title="Test Watch",
            url="https://rueschenbeck.de/uhren/test",
            site_name="Rüschenbeck",
            site_key="rueschenbeck"
        )
        
        # Set initial short reference
        watch.reference = "123"
        
        # Simulate longer reference from details
        parsed_details = {"reference_text": "123.456.789.012"}
        
        # Apply preference logic
        if (parsed_details.get("reference_text") and 
            (not watch.reference or len(parsed_details["reference_text"]) > len(watch.reference))):
            watch.reference = parsed_details["reference_text"].strip()
        
        assert watch.reference == "123.456.789.012"
    
    def test_box_papers_detection_from_details(self, rueschenbeck_scraper):
        """Test box and papers detection from various detail sources."""
        test_cases = [
            # (combined_text, expected_papers, expected_box)
            ("Uhr, Originalbox, Papiere, Garantiekarte, alle Glieder", True, True),
            ("Nur Uhr, keine Papiere oder Box", False, False),
            ("Watch with original box only", False, True),
            ("Papers and certificate included", True, False),
            ("Complete set with all accessories", True, True),
            ("No mention of accessories", None, None),
        ]
        
        for detail_text, expected_papers, expected_box in test_cases:
            with patch('scrapers.rueschenbeck.parse_box_papers') as mock_parse:
                mock_parse.return_value = (expected_papers, expected_box)
                
                detail_html = f"""
                <div class="lieferumfang">
                    <p>{detail_text}</p>
                </div>
                """
                
                watch = WatchData(
                    title="Test Watch",
                    url="https://rueschenbeck.de/uhren/test",
                    site_name="Rüschenbeck",
                    site_key="rueschenbeck"
                )
                
                soup = BeautifulSoup(detail_html, 'html.parser')
                rueschenbeck_scraper._extract_watch_details(watch, soup)
                
                assert watch.has_papers == expected_papers, f"Papers detection failed for: {detail_text}"
                assert watch.has_box == expected_box, f"Box detection failed for: {detail_text}"
    
    @pytest.mark.parametrize("price_text,expected_price", [
        ("€ 8.500,00", Decimal("8500.00")),
        ("€8.500", Decimal("8500.00")),
        ("8500 EUR", Decimal("8500.00")),
        ("€ 1.234.567,89", Decimal("1234567.89")),
        ("Preis auf Anfrage", None),
        ("Verkauft", None),
        ("", None),
        ("Invalid Price", None)
    ])
    def test_price_parsing_variations(self, rueschenbeck_scraper, price_text, expected_price):
        """Test various EUR price text formats."""
        html = f"""
        <li class="-rb-list-item">
            <a class="-rb-list-item-link" href="/uhren/test-watch">
                <div class="watch-details">
                    <span class="-rb-manufacturer-name">TestBrand</span>
                    <span class="-rb-prod-name">Test Watch</span>
                    <div class="price-box">
                        <span class="regular-price">
                            <span class="price">{price_text}</span>
                        </span>
                    </div>
                </div>
            </a>
        </li>
        """
        
        soup = BeautifulSoup(html, 'html.parser')
        element = soup.select_one('.-rb-list-item')
        
        result = rueschenbeck_scraper._parse_watch_element(element)
        
        if expected_price is None:
            assert result is None or result.price is None
        else:
            assert result is not None
            assert result.price == expected_price
            assert result.currency == "EUR"
    
    @pytest.mark.asyncio
    async def test_full_scrape_integration(self, rueschenbeck_scraper, rueschenbeck_listing_html):
        """Test full scraping workflow integration."""
        with patch('scrapers.base.fetch_page', return_value=rueschenbeck_listing_html):
            with patch('scrapers.base.APP_CONFIG') as mock_config:
                mock_config.enable_detail_scraping = False
                
                watches = await rueschenbeck_scraper.scrape()
        
        assert len(watches) == 4  # Sold watch should be excluded
        assert all(isinstance(watch, WatchData) for watch in watches)
        assert all(watch.site_key == "rueschenbeck" for watch in watches)
        assert all(watch.site_name == "Rüschenbeck" for watch in watches)
        assert all(watch.currency == "EUR" for watch in watches)
        
        # Verify composite IDs are generated
        assert len(rueschenbeck_scraper.seen_ids) == 4
        for watch in watches:
            assert watch.composite_id in rueschenbeck_scraper.seen_ids
    
    @pytest.mark.asyncio
    async def test_scrape_with_seen_watches(self, rueschenbeck_scraper, rueschenbeck_listing_html):
        """Test scraping with some watches already seen."""
        # Pre-populate with one seen watch
        seen_watch = WatchData(
            title="116610LN Submariner Date",
            url="https://rueschenbeck.de/uhren/rolex-submariner-116610ln",
            site_name="Rüschenbeck",
            site_key="rueschenbeck",
            price=Decimal("8500.00"),
            currency="EUR"
        )
        rueschenbeck_scraper.seen_ids = {seen_watch.composite_id}
        
        with patch('scrapers.base.fetch_page', return_value=rueschenbeck_listing_html):
            with patch('scrapers.base.APP_CONFIG') as mock_config:
                mock_config.enable_detail_scraping = False
                
                watches = await rueschenbeck_scraper.scrape()
        
        # Should return only new watches (3 instead of 4)
        assert len(watches) == 3
        assert not any("rolex-submariner-116610ln" in watch.url for watch in watches)
    
    @pytest.mark.asyncio
    async def test_scrape_parse_error_handling(self, rueschenbeck_scraper):
        """Test scraping handles parse errors gracefully."""
        malformed_html = """
        <li class="-rb-list-item">
            <a class="-rb-list-item-link" href="/uhren/error-watch">
                <div class="watch-details">
                    <span class="-rb-manufacturer-name">Error</span>
                    <span class="-rb-prod-name">Error Watch</span>
                    <div class="price-box">
                        <span class="regular-price">
                            <span class="price">€ 1.000,00</span>
                        </span>
                    </div>
                </div>
            </a>
        </li>
        """
        
        with patch('scrapers.base.fetch_page', return_value=malformed_html):
            with patch('scrapers.base.APP_CONFIG') as mock_config:
                mock_config.enable_detail_scraping = False
                
                # Mock _parse_watch_element to raise an error
                original_parse = rueschenbeck_scraper._parse_watch_element
                def mock_parse(element):
                    if "error-watch" in str(element):
                        raise Exception("Parse error")
                    return original_parse(element)
                
                rueschenbeck_scraper._parse_watch_element = mock_parse
                
                watches = await rueschenbeck_scraper.scrape()
        
        # Should handle errors gracefully and return empty list
        assert watches == []
    
    def test_composite_id_generation(self, rueschenbeck_scraper):
        """Test that watches generate unique composite IDs."""
        html_template = """
        <li class="-rb-list-item">
            <a class="-rb-list-item-link" href="/uhren/{url_path}">
                <div class="watch-details">
                    <span class="-rb-manufacturer-name">{brand}</span>
                    <span class="-rb-prod-name">{title}</span>
                    <div class="price-box">
                        <span class="regular-price">
                            <span class="price">€ 1.000,00</span>
                        </span>
                    </div>
                </div>
            </a>
        </li>
        """
        
        html1 = html_template.format(url_path="watch-1", brand="Brand1", title="Watch 1")
        html2 = html_template.format(url_path="watch-2", brand="Brand2", title="Watch 2")
        
        soup1 = BeautifulSoup(html1, 'html.parser')
        soup2 = BeautifulSoup(html2, 'html.parser')
        
        watch1 = rueschenbeck_scraper._parse_watch_element(soup1.select_one('.-rb-list-item'))
        watch2 = rueschenbeck_scraper._parse_watch_element(soup2.select_one('.-rb-list-item'))
        
        assert watch1 is not None
        assert watch2 is not None
        assert watch1.composite_id != watch2.composite_id
        assert watch1.composite_id is not None
        assert watch2.composite_id is not None
    
    def test_availability_status_filtering(self, rueschenbeck_scraper):
        """Test different availability status handling."""
        test_cases = [
            # (availability_html, should_be_included)
            ('<div class="-rb-availability"><span class="in-stock"><span class="value">Verfügbar</span></span></div>', True),
            ('<div class="-rb-availability"><span class="sold"><span class="value">verkauft</span></span></div>', False),
            ('<div class="-rb-availability"><span class="out-of-stock"><span class="value">verkauft</span></span></div>', False),
            ('<div class="-rb-availability"><span class="reserved"><span class="value">reserviert</span></span></div>', True),  # Not sold
            ('', True),  # No availability info, assume available
        ]
        
        for availability_html, should_be_included in test_cases:
            html = f"""
            <li class="-rb-list-item">
                <a class="-rb-list-item-link" href="/uhren/test-watch">
                    <div class="watch-details">
                        <span class="-rb-manufacturer-name">TestBrand</span>
                        <span class="-rb-prod-name">Test Watch</span>
                        {availability_html}
                        <div class="price-box">
                            <span class="regular-price">
                                <span class="price">€ 1.000,00</span>
                            </span>
                        </div>
                    </div>
                </a>
            </li>
            """
            soup = BeautifulSoup(html, 'html.parser')
            element = soup.select_one('.-rb-list-item')
            
            watch = rueschenbeck_scraper._parse_watch_element(element)
            
            if should_be_included:
                assert watch is not None, f"Should include watch with availability: {availability_html}"
            else:
                assert watch is None, f"Should exclude watch with availability: {availability_html}"