"""Comprehensive tests for Grimmeissen scraper."""

import pytest
import json
from decimal import Decimal
from unittest.mock import Mock, AsyncMock, patch
from bs4 import BeautifulSoup
import aiohttp

from scrapers.grimmeissen import GrimmeissenScraper
from models import WatchData
from config import SiteConfig


@pytest.fixture
def grimmeissen_config():
    """Grimmeissen site configuration for testing."""
    return SiteConfig(
        name="Grimmeissen",
        key="grimmeissen", 
        url="https://grimmeissen.de/uhren",
        webhook_env_var="GRIMMEISSEN_WEBHOOK_URL",
        color=0x8B4513,
        base_url="https://grimmeissen.de",
        known_brands={
            "rolex": "Rolex",
            "omega": "Omega", 
            "breitling": "Breitling",
            "iwc": "IWC",
            "jaeger lecoultre": "Jaeger LeCoultre",
            "patek philippe": "Patek Philippe"
        },
        condition_mappings={
            "neu": "★★★★★",
            "sehr gut": "★★★★☆", 
            "gut": "★★★☆☆",
            "gebraucht": "★★☆☆☆",
            "vintage": "★★☆☆☆"
        }
    )


@pytest.fixture 
def grimmeissen_scraper(grimmeissen_config, mock_aiohttp_session, mock_logger):
    """Create Grimmeissen scraper instance for testing."""
    return GrimmeissenScraper(grimmeissen_config, mock_aiohttp_session, mock_logger)


@pytest.fixture
def grimmeissen_listing_html():
    """Sample HTML from Grimmeissen listing page."""
    return """
    <!DOCTYPE html>
    <html>
    <body>
        <main class="watches-listing">
            <article class="watch">
                <figure>
                    <a href="/uhren/rolex-submariner-116610ln">
                        <img data-src="https://grimmeissen.de/images/rolex-submariner-116610ln-1.jpg" 
                             alt="Rolex Submariner Date"/>
                    </a>
                </figure>
                <section class="fh">
                    <h1>
                        <span><a href="/brands/rolex">Rolex</a></span>
                        Submariner Date
                    </h1>
                    <p>€ 8.500</p>
                </section>
            </article>
            
            <article class="watch">
                <figure>
                    <a href="/uhren/omega-speedmaster-311">
                        <img data-src="https://grimmeissen.de/images/omega-speedmaster-311.jpg"
                             alt="Omega Speedmaster"/>
                    </a>
                </figure>
                <section class="fh">
                    <h1>
                        <span><a href="/brands/omega">Omega</a></span>
                        Speedmaster Professional Moonwatch
                    </h1>
                    <p>€ 4.200</p>
                </section>
            </article>
            
            <article class="watch">
                <figure>
                    <a href="/uhren/patek-philippe-5711">
                        <img data-src="https://grimmeissen.de/images/patek-philippe-5711.jpg"
                             alt="Patek Philippe Nautilus"/>
                    </a>
                </figure>
                <section class="fh">
                    <h1>No Brand Watch</h1>
                    <p>Price on Request</p>
                </section>
            </article>
        </main>
    </body>
    </html>
    """


@pytest.fixture
def grimmeissen_detail_html():
    """Sample HTML from Grimmeissen detail page."""
    return """
    <!DOCTYPE html>
    <html>
    <body>
        <div class="c-7 do-lefty">
            <h1 class="lowpad-b">
                <span><a href="/brands/rolex">Rolex</a></span>
                Submariner Date 116610LN
            </h1>
            
            <table>
                <tr>
                    <th>Referenz:</th>
                    <td>116610LN</td>
                </tr>
                <tr>
                    <th>Zustand:</th>
                    <td>Sehr gut</td>
                </tr>
                <tr>
                    <th>Gehäuse:</th>
                    <td>Edelstahl</td>
                </tr>
                <tr>
                    <th>Jahr:</th>
                    <td>2020</td>
                </tr>
                <tr>
                    <th>Durchmesser:</th>
                    <td>40mm</td>
                </tr>
            </table>
            
            <h3>Details</h3>
            <table>
                <tr>
                    <th>Lieferumfang:</th>
                    <td>Uhr, Originalbox, Papiere, Zertifikat</td>
                </tr>
            </table>
        </div>
    </body>
    </html>
    """


@pytest.fixture
def grimmeissen_edge_case_html():
    """HTML with edge cases for testing."""
    return """
    <!DOCTYPE html>
    <html>
    <body>
        <main class="watches-listing">
            <!-- Watch with missing image -->
            <article class="watch">
                <figure>
                    <a href="/uhren/missing-image-watch"></a>
                </figure>
                <section class="fh">
                    <h1>Watch Without Image</h1>
                    <p>€ 1.000</p>
                </section>
            </article>
            
            <!-- Watch with no price -->
            <article class="watch">
                <figure>
                    <a href="/uhren/no-price-watch">
                        <img data-src="https://grimmeissen.de/images/watch.jpg" alt="Watch"/>
                    </a>
                </figure>
                <section class="fh">
                    <h1>Watch Without Price</h1>
                    <p></p>
                </section>
            </article>
            
            <!-- Watch with malformed price -->
            <article class="watch">
                <figure>
                    <a href="/uhren/malformed-price-watch">
                        <img data-src="https://grimmeissen.de/images/watch.jpg" alt="Watch"/>
                    </a>
                </figure>
                <section class="fh">
                    <h1>Watch With Bad Price</h1>
                    <p>Price varies</p>
                </section>
            </article>
            
            <!-- Watch with no link -->
            <article class="watch">
                <figure>
                    <a></a>
                </figure>
                <section class="fh">
                    <h1>Watch Without Link</h1>
                    <p>€ 2.000</p>
                </section>
            </article>
        </main>
    </body>
    </html>
    """


@pytest.mark.asyncio
class TestGrimmeissenScraper:
    """Test suite for Grimmeissen scraper."""

    async def test_extract_watches_success(self, grimmeissen_scraper, grimmeissen_listing_html):
        """Test successful watch extraction from listing page."""
        soup = BeautifulSoup(grimmeissen_listing_html, 'html.parser')
        watches = await grimmeissen_scraper._extract_watches(soup)
        
        assert len(watches) == 3
        
        # Test first watch (Rolex)
        rolex_watch = watches[0]
        assert rolex_watch.title == "Rolex Submariner Date"
        assert rolex_watch.brand == "Rolex"
        assert rolex_watch.model == "Submariner Date"
        assert rolex_watch.price == Decimal("8500")
        assert rolex_watch.currency == "EUR"
        assert rolex_watch.url == "https://grimmeissen.de/uhren/rolex-submariner-116610ln"
        assert rolex_watch.image_url == "https://grimmeissen.de/images/rolex-submariner-116610ln-1.jpg"
        assert rolex_watch.site_name == "Grimmeissen"
        assert rolex_watch.site_key == "grimmeissen"
        
        # Test second watch (Omega)
        omega_watch = watches[1]
        assert omega_watch.title == "Omega Speedmaster Professional Moonwatch"
        assert omega_watch.brand == "Omega"
        assert omega_watch.model == "Speedmaster Professional Moonwatch"
        assert omega_watch.price == Decimal("4200")
        
        # Test third watch (no brand)
        no_brand_watch = watches[2]
        assert no_brand_watch.title == "No Brand Watch"
        assert no_brand_watch.brand is None
        assert no_brand_watch.model == "No Brand Watch"
        assert no_brand_watch.price is None  # "Price on Request" should not parse

    async def test_extract_watches_edge_cases(self, grimmeissen_scraper, grimmeissen_edge_case_html):
        """Test watch extraction with edge cases."""
        soup = BeautifulSoup(grimmeissen_edge_case_html, 'html.parser')
        watches = await grimmeissen_scraper._extract_watches(soup)
        
        # Should only get watches with valid URLs
        assert len(watches) == 3  # Missing image, no price, and malformed price should still work
        
        # Watch without image should work
        watch_no_image = next((w for w in watches if "missing-image" in w.url), None)
        assert watch_no_image is not None
        assert watch_no_image.image_url is None
        assert watch_no_image.price == Decimal("1000")
        
        # Watch without price should work
        watch_no_price = next((w for w in watches if "no-price" in w.url), None)
        assert watch_no_price is not None
        assert watch_no_price.price is None
        
        # Watch with malformed price should work
        watch_bad_price = next((w for w in watches if "malformed-price" in w.url), None)
        assert watch_bad_price is not None
        assert watch_bad_price.price is None  # "Price varies" should not parse

    async def test_extract_watch_details(self, grimmeissen_scraper, grimmeissen_detail_html):
        """Test detailed information extraction from detail page."""
        # Create a sample watch
        watch = WatchData(
            title="Test Watch",
            url="https://grimmeissen.de/uhren/test-watch",
            site_name="Grimmeissen",
            site_key="grimmeissen"
        )
        
        soup = BeautifulSoup(grimmeissen_detail_html, 'html.parser')
        await grimmeissen_scraper._extract_watch_details(watch, soup)
        
        # Check updated fields
        assert watch.title == "Rolex Submariner Date 116610LN"
        assert watch.brand == "Rolex"
        assert watch.model == "Submariner Date 116610LN"
        assert watch.reference == "116610LN"
        assert watch.condition == "★★★★☆"  # "Sehr gut" maps to 4 stars
        assert watch.case_material == "Edelstahl"
        assert watch.year == "2020"
        assert watch.diameter == "40mm"
        assert watch.has_papers is True
        assert watch.has_box is True

    async def test_extract_watch_details_minimal_data(self, grimmeissen_scraper):
        """Test detail extraction with minimal data."""
        minimal_html = """
        <html>
            <body>
                <div class="c-7 do-lefty">
                    <h1 class="lowpad-b">Simple Watch</h1>
                </div>
            </body>
        </html>
        """
        
        watch = WatchData(
            title="Original Title",
            url="https://grimmeissen.de/uhren/test-watch", 
            site_name="Grimmeissen",
            site_key="grimmeissen"
        )
        
        soup = BeautifulSoup(minimal_html, 'html.parser')
        await grimmeissen_scraper._extract_watch_details(watch, soup)
        
        # Should update title but keep other fields as original
        assert watch.title == "Simple Watch"
        assert watch.reference is None
        assert watch.condition is None

    def test_parse_details_from_table_th_td(self, grimmeissen_scraper):
        """Test table parsing helper method."""
        table_html = """
        <table>
            <tr>
                <th>Referenz:</th>
                <td>116610LN</td>
            </tr>
            <tr>
                <th>Zustand:</th>
                <td>Sehr gut</td>
            </tr>
            <tr>
                <th>Jahr:</th>
                <td>2020</td>
            </tr>
        </table>
        """
        
        soup = BeautifulSoup(table_html, 'html.parser')
        table = soup.find('table')
        
        headers_map = {
            "Referenz": "reference",
            "Zustand": "condition_text",
            "Jahr": "year_text"
        }
        
        details = grimmeissen_scraper._parse_details_from_table_th_td(table, headers_map)
        
        assert details["reference"] == "116610LN"
        assert details["condition_text"] == "Sehr gut"
        assert details["year_text"] == "2020"

    def test_parse_details_from_table_empty(self, grimmeissen_scraper):
        """Test table parsing with empty table."""
        details = grimmeissen_scraper._parse_details_from_table_th_td(None, {})
        assert details == {}

    def test_parse_details_from_table_malformed(self, grimmeissen_scraper):
        """Test table parsing with malformed HTML."""
        malformed_html = """
        <table>
            <tr>
                <th>Only Header</th>
            </tr>
            <tr>
                <td>Only Data</td>
            </tr>
            <tr>
                <th>Complete:</th>
                <td>Value</td>
            </tr>
        </table>
        """
        
        soup = BeautifulSoup(malformed_html, 'html.parser')
        table = soup.find('table')
        
        headers_map = {"Complete": "complete_field"}
        details = grimmeissen_scraper._parse_details_from_table_th_td(table, headers_map)
        
        # Should only get the complete row
        assert details == {"complete_field": "Value"}

    def test_parse_watch_element_missing_elements(self, grimmeissen_scraper):
        """Test parsing watch element with missing required elements."""
        # No link
        no_link_html = """
        <article class="watch">
            <figure></figure>
            <section class="fh">
                <h1>Test Watch</h1>
                <p>€ 1.000</p>
            </section>
        </article>
        """
        
        soup = BeautifulSoup(no_link_html, 'html.parser')
        watch_tag = soup.find('article')
        
        result = grimmeissen_scraper._parse_watch_element(watch_tag)
        assert result is None

    async def test_scraper_with_mock_data(self, grimmeissen_scraper):
        """Test full scraping flow with mocked data."""
        # Mock the seen_ids
        grimmeissen_scraper.set_seen_ids(set())
        
        # Mock fetch_page to return our test HTML
        with patch('scrapers.grimmeissen.fetch_page') as mock_fetch:
            mock_fetch.return_value = """
            <article class="watch">
                <figure>
                    <a href="/uhren/test-watch">
                        <img data-src="/images/test.jpg" alt="Test"/>
                    </a>
                </figure>
                <section class="fh">
                    <h1><span><a href="/brands/rolex">Rolex</a></span> Test Watch</h1>
                    <p>€ 5.000</p>
                </section>
            </article>
            """
            
            watches = await grimmeissen_scraper.scrape()
            
            assert len(watches) == 1
            assert watches[0].title == "Rolex Test Watch"
            assert watches[0].brand == "Rolex"
            assert watches[0].price == Decimal("5000")

    async def test_scraper_error_handling(self, grimmeissen_scraper):
        """Test scraper error handling."""
        # Mock fetch_page to return None (simulating network error)
        with patch('scrapers.grimmeissen.fetch_page') as mock_fetch:
            mock_fetch.return_value = None
            
            watches = await grimmeissen_scraper.scrape()
            assert watches == []

    def test_condition_mapping(self, grimmeissen_scraper):
        """Test condition text mapping."""
        # Test with actual condition parsing
        test_html = """
        <html>
            <body>
                <div class="c-7 do-lefty">
                    <table>
                        <tr>
                            <th>Zustand:</th>
                            <td>Neu</td>
                        </tr>
                    </table>
                </div>
            </body>
        </html>
        """
        
        watch = WatchData(
            title="Test Watch",
            url="https://grimmeissen.de/uhren/test",
            site_name="Grimmeissen", 
            site_key="grimmeissen"
        )
        
        soup = BeautifulSoup(test_html, 'html.parser')
        
        # Mock parse_condition to test the flow
        with patch('scrapers.grimmeissen.parse_condition') as mock_parse:
            mock_parse.return_value = "★★★★★"
            
            grimmeissen_scraper._extract_watch_details(watch, soup)
            
            mock_parse.assert_called_once_with(
                "Neu", 
                "grimmeissen",
                grimmeissen_scraper.config.condition_mappings
            )

    async def test_box_papers_detection(self, grimmeissen_scraper):
        """Test box and papers detection."""
        test_cases = [
            ("Uhr, Originalbox, Papiere", True, True),
            ("Uhr, Box", False, True), 
            ("Uhr, Zertifikat, Papiere", True, False),
            ("Nur Uhr", False, False),
            ("Uhr, Originalverpackung, Garantiekarte", True, True),
        ]
        
        for lieferumfang_text, expected_papers, expected_box in test_cases:
            detail_html = f"""
            <div class="c-7 do-lefty">
                <h3>Details</h3>
                <table>
                    <tr>
                        <th>Lieferumfang:</th>
                        <td>{lieferumfang_text}</td>
                    </tr>
                </table>
            </div>
            """
            
            watch = WatchData(
                title="Test Watch",
                url="https://grimmeissen.de/uhren/test",
                site_name="Grimmeissen",
                site_key="grimmeissen"
            )
            
            soup = BeautifulSoup(detail_html, 'html.parser')
            await grimmeissen_scraper._extract_watch_details(watch, soup)
            
            assert watch.has_papers == expected_papers, f"Papers detection failed for: {lieferumfang_text}"
            assert watch.has_box == expected_box, f"Box detection failed for: {lieferumfang_text}"

    @pytest.mark.parametrize("price_text,expected_price", [
        ("€ 8.500", Decimal("8500")),
        ("€8,500.00", Decimal("8500")),
        ("8.500 EUR", Decimal("8500")),
        ("Price on Request", None),
        ("Verkauft", None),
        ("", None),
        ("Invalid Price", None)
    ])
    def test_price_parsing_variations(self, grimmeissen_scraper, price_text, expected_price):
        """Test various price text formats."""
        watch_html = f"""
        <article class="watch">
            <figure>
                <a href="/uhren/test-watch">
                    <img data-src="/images/test.jpg" alt="Test"/>
                </a>
            </figure>
            <section class="fh">
                <h1>Test Watch</h1>
                <p>{price_text}</p>
            </section>
        </article>
        """
        
        soup = BeautifulSoup(watch_html, 'html.parser')
        watch_tag = soup.find('article')
        
        result = grimmeissen_scraper._parse_watch_element(watch_tag)
        
        if expected_price is None:
            assert result.price is None
        else:
            assert result.price == expected_price