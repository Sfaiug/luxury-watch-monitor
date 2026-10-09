"""Comprehensive tests for Juwelier Exchange scraper implementation."""

import pytest
import json
import asyncio
from unittest.mock import AsyncMock, Mock, patch
from bs4 import BeautifulSoup
from decimal import Decimal
from urllib.parse import urljoin

from scrapers.juwelier_exchange import JuwelierExchangeScraper
from models import WatchData
from config import SiteConfig


@pytest.fixture
def juwelier_exchange_config():
    """Juwelier Exchange site configuration for testing."""
    return SiteConfig(
        name="Juwelier Exchange",
        key="juwelier_exchange",
        url="https://juwelier-exchange.de/uhren",
        webhook_env_var="JUWELIER_EXCHANGE_WEBHOOK_URL",
        color=0x1E90FF,
        base_url="https://juwelier-exchange.de",
        known_brands={
            "rolex": "Rolex",
            "patek philippe": "Patek Philippe",
            "audemars piguet": "Audemars Piguet",
            "omega": "Omega",
            "breitling": "Breitling",
            "iwc": "IWC",
            "cartier": "Cartier",
            "jaeger lecoultre": "Jaeger LeCoultre"
        }
    )


@pytest.fixture
def juwelier_exchange_scraper(juwelier_exchange_config, mock_aiohttp_session, mock_logger):
    """Juwelier Exchange scraper instance for testing."""
    return JuwelierExchangeScraper(juwelier_exchange_config, mock_aiohttp_session, mock_logger)


@pytest.fixture
def juwelier_exchange_listing_html():
    """Realistic Juwelier Exchange listing page HTML."""
    return """
    <!DOCTYPE html>
    <html lang="de">
    <head>
        <title>Juwelier Exchange - Luxusuhren</title>
    </head>
    <body>
        <div class="product-listing">
            <!-- First watch - Rolex with srcset -->
            <div class="card product-box" data-product-information='{"id": 12345, "price": 8500.0}'>
                <a class="card-body-link" href="/uhren/rolex-submariner-date-116610ln">
                    <img class="product-image" 
                         src="/media/images/rolex-submariner-116610ln-400x400.jpg"
                         srcset="/media/images/rolex-submariner-116610ln-400x400.webp 400w,
                                 /media/images/rolex-submariner-116610ln-800x800.webp 800w,
                                 /media/images/rolex-submariner-116610ln-1920x1920.webp 1920w"
                         alt="Rolex Submariner Date" />
                    <span class="product-price">€ 8.500,00</span>
                </a>
            </div>
            
            <!-- Second watch - Omega without srcset -->
            <div class="card product-box" data-product-information='{"id": 12346, "price": 4200.0}'>
                <a class="card-body-link" href="/uhren/omega-speedmaster-professional">
                    <img class="product-image" 
                         src="/media/images/omega-speedmaster-400x400.jpg"
                         alt="Omega Speedmaster" />
                    <span class="product-price">€ 4.200,00</span>
                </a>
            </div>
            
            <!-- Third watch - Patek Philippe with complex srcset -->
            <div class="card product-box" data-product-information='{"id": 12347, "price": 32000.0}'>
                <a class="card-body-link" href="/uhren/patek-philippe-calatrava-5196g">
                    <img class="product-image" 
                         src="/media/images/patek-calatrava-400x400.jpg"
                         srcset="/media/images/patek-calatrava-400x400.webp 400w,
                                 /media/images/patek-calatrava-800x800.jpg 800w,
                                 /media/images/patek-calatrava-1920x1920.webp 1920w"
                         alt="Patek Philippe Calatrava" />
                    <span class="product-price">€ 32.000,00</span>
                </a>
            </div>
            
            <!-- Fourth watch - Missing price -->
            <div class="card product-box" data-product-information='{"id": 12348}'>
                <a class="card-body-link" href="/uhren/iwc-pilot-watch">
                    <img class="product-image" 
                         src="/media/images/iwc-pilot-400x400.jpg"
                         alt="IWC Pilot" />
                    <span class="product-price"></span>
                </a>
            </div>
        </div>
    </body>
    </html>
    """


@pytest.fixture
def juwelier_exchange_detail_html():
    """Realistic Juwelier Exchange detail page HTML with JSON-LD."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Rolex Submariner Date 116610LN - Juwelier Exchange</title>
        <script type="application/ld+json">
        {
            "@context": "https://schema.org/",
            "@type": "Product",
            "name": "Rolex Submariner Date Ref. 116610LN",
            "description": "Rolex Submariner Date in Edelstahl mit schwarzem Zifferblatt und Keramiklünette. Baujahr 2020, ausgezeichneter Zustand mit Box und Papieren.",
            "brand": {
                "@type": "Brand",
                "name": "Rolex"
            },
            "offers": {
                "@type": "Offer",
                "price": "8500.00",
                "priceCurrency": "EUR"
            }
        }
        </script>
    </head>
    <body>
        <div class="product-detail">
            <h1 class="product-detail-name">Herrenuhr Rolex 'Submariner' Ref. 116610LN</h1>
            
            <table class="product-detail-properties-table">
                <tr class="properties-row">
                    <th class="properties-label">Artikelnummer:</th>
                    <td class="properties-value">116610LN</td>
                </tr>
                <tr class="properties-row">
                    <th class="properties-label">Marke:</th>
                    <td class="properties-value">Rolex</td>
                </tr>
                <tr class="properties-row">
                    <th class="properties-label">Zustand:</th>
                    <td class="properties-value">Ausgezeichnet</td>
                </tr>
                <tr class="properties-row">
                    <th class="properties-label">Art der Legierung:</th>
                    <td class="properties-value">Edelstahl</td>
                </tr>
                <tr class="properties-row">
                    <th class="properties-label">Legierung:</th>
                    <td class="properties-value">904L</td>
                </tr>
            </table>
            
            <div class="product-detail-description-text" itemprop="description">
                <p>Die Rolex Submariner Date Ref. 116610LN ist eine der begehrtesten Taucheruhren der Welt. 
                Hergestellt im Jahr 2020, verfügt sie über ein 40mm Edelstahlgehäuse mit schwarzer Keramiklünette.</p>
                
                <p>Gehäusedurchmesser: 40 mm</p>
                
                <p>Lieferumfang: Originalbox, Garantiekarte, Bedienungsanleitung und alle Papiere sind vorhanden.</p>
                
                <p>Zustand: Ausgezeichneter Zustand mit minimalen Gebrauchsspuren. Das Gehäuse aus 904L Edelstahl 
                zeigt keine sichtbaren Kratzer. Die Keramiklünette ist in perfektem Zustand.</p>
            </div>
        </div>
    </body>
    </html>
    """


@pytest.fixture
def juwelier_exchange_minimal_detail_html():
    """Minimal detail page without JSON-LD."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Omega Speedmaster - Juwelier Exchange</title>
    </head>
    <body>
        <div class="product-detail">
            <h1 class="product-detail-name">Omega Speedmaster Professional</h1>
            
            <table class="product-detail-properties-table">
                <tr class="properties-row">
                    <th class="properties-label">Artikelnummer:</th>
                    <td class="properties-value">311.30.42.30.01.005</td>
                </tr>
                <tr class="properties-row">
                    <th class="properties-label">Material:</th>
                    <td class="properties-value">Edelstahl</td>
                </tr>
            </table>
            
            <div class="product-detail-description-text" itemprop="description">
                <p>Omega Speedmaster Professional aus dem Jahr 2019.</p>
                <p>Gehäusedurchmesser ca. 42 mm</p>
                <p>Nur Uhr, keine Papiere oder Box vorhanden.</p>
            </div>
        </div>
    </body>
    </html>
    """


@pytest.fixture
def juwelier_exchange_complex_detail_html():
    """Complex detail page with various material types."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Patek Philippe Calatrava - Juwelier Exchange</title>
        <script type="application/ld+json">
        {
            "@context": "https://schema.org/",
            "@type": "Product",
            "name": "Patek Philippe Calatrava Ref. 5196G-001",
            "brand": {
                "@type": "Brand", 
                "name": "Patek Philippe"
            }
        }
        </script>
    </head>
    <body>
        <div class="product-detail">
            <h1 class="product-detail-name">Herrenuhr Patek Philippe 'Calatrava' Ref. 5196G-001</h1>
            
            <table class="product-detail-properties-table">
                <tr class="properties-row">
                    <th class="properties-label">Art der Legierung:</th>
                    <td class="properties-value">Weißgold</td>
                </tr>
                <tr class="properties-row">
                    <th class="properties-label">Legierung:</th>
                    <td class="properties-value">750</td>
                </tr>
            </table>
            
            <div class="product-detail-description-text" itemprop="description">
                <p>Patek Philippe Calatrava in 750er Weißgold, Baujahr 2018.</p>
                <p>Durchmesser von 37 mm</p>
                <p>Gehäuse aus Weißgold mit handgefertigtem Zifferblatt.</p>
                <p>Lieferumfang: Uhr, Originalbox, Papiere, Zertifikat</p>
            </div>
        </div>
    </body>
    </html>
    """


@pytest.fixture
def juwelier_exchange_empty_html():
    """Empty Juwelier Exchange listing page."""
    return """
    <html>
    <body>
        <div class="no-products-found">
            <p>Keine Uhren gefunden.</p>
        </div>
    </body>
    </html>
    """


@pytest.fixture
def juwelier_exchange_malformed_html():
    """Malformed Juwelier Exchange listing with missing elements."""
    return """
    <html>
    <body>
        <div class="product-listing">
            <!-- Watch without link -->
            <div class="card product-box" data-product-information='{"id": 99999}'>
                <img class="product-image" src="/images/no-link.jpg" alt="No Link" />
                <span class="product-price">€ 1.000,00</span>
            </div>
            
            <!-- Watch with complete data -->
            <div class="card product-box" data-product-information='{"id": 88888, "price": 2000.0}'>
                <a class="card-body-link" href="/uhren/complete-watch">
                    <img class="product-image" src="/images/complete.jpg" alt="Complete" />
                    <span class="product-price">€ 2.000,00</span>
                </a>
            </div>
        </div>
    </body>
    </html>
    """


class TestJuwelierExchangeScraper:
    """Test Juwelier Exchange scraper implementation."""
    
    def test_initialization(self, juwelier_exchange_config, mock_aiohttp_session, mock_logger):
        """Test scraper initialization."""
        scraper = JuwelierExchangeScraper(juwelier_exchange_config, mock_aiohttp_session, mock_logger)
        
        assert scraper.config == juwelier_exchange_config
        assert scraper.session == mock_aiohttp_session
        assert len(scraper.seen_ids) == 0
    
    @pytest.mark.asyncio
    async def test_extract_watches_success(self, juwelier_exchange_scraper, juwelier_exchange_listing_html):
        """Test successful watch extraction from listing page."""
        soup = BeautifulSoup(juwelier_exchange_listing_html, 'html.parser')
        
        watches = await juwelier_exchange_scraper._extract_watches(soup)
        
        assert len(watches) == 4  # All watches including one without price
        
        # Test first watch - with srcset
        rolex_watch = watches[0]
        assert rolex_watch.title == "Unknown Watch"  # the made-up card has no name
        assert rolex_watch.url == "https://juwelier-exchange.de/uhren/rolex-submariner-date-116610ln"
        assert rolex_watch.price == Decimal("8500.00")
        assert rolex_watch.currency == "EUR"
        # Should prefer 1920x1920.webp from srcset
        assert "1920x1920.webp" in rolex_watch.image_url
        assert rolex_watch.site_name == "Juwelier Exchange"
        assert rolex_watch.site_key == "juwelier_exchange"
        
        # Test second watch - no srcset, fallback to src
        omega_watch = watches[1]
        assert omega_watch.url == "https://juwelier-exchange.de/uhren/omega-speedmaster-professional"
        assert omega_watch.price == Decimal("4200.00")
        assert omega_watch.image_url == "https://juwelier-exchange.de/media/images/omega-speedmaster-400x400.jpg"
        
        # Test third watch - complex srcset with .jpg and .webp mixed
        patek_watch = watches[2]
        assert patek_watch.price == Decimal("32000.00")
        # Should prefer .webp over .jpg
        assert "webp" in patek_watch.image_url
        
        # Test fourth watch - missing price
        iwc_watch = watches[3]
        assert iwc_watch.price is None
        assert iwc_watch.url == "https://juwelier-exchange.de/uhren/iwc-pilot-watch"
    
    @pytest.mark.asyncio
    async def test_extract_watches_empty_page(self, juwelier_exchange_scraper, juwelier_exchange_empty_html):
        """Test extraction from empty listing page."""
        soup = BeautifulSoup(juwelier_exchange_empty_html, 'html.parser')
        
        watches = await juwelier_exchange_scraper._extract_watches(soup)
        
        assert watches == []
    
    @pytest.mark.asyncio
    async def test_extract_watches_malformed_elements(self, juwelier_exchange_scraper, juwelier_exchange_malformed_html):
        """Test extraction with malformed/missing elements."""
        soup = BeautifulSoup(juwelier_exchange_malformed_html, 'html.parser')
        
        watches = await juwelier_exchange_scraper._extract_watches(soup)
        
        # Should return only complete watches
        assert len(watches) == 1
        
        watch = watches[0]
        assert watch.price == Decimal("2000.00")
        assert watch.url == "https://juwelier-exchange.de/uhren/complete-watch"
    
    def test_parse_watch_element_missing_link(self, juwelier_exchange_scraper):
        """Test parsing element without link returns None."""
        html = """
        <div class="card product-box" data-product-information='{"id": 12345}'>
            <img class="product-image" src="/images/no-link.jpg" alt="No Link" />
            <span class="product-price">€ 1.000,00</span>
        </div>
        """
        soup = BeautifulSoup(html, 'html.parser')
        element = soup.select_one('.card.product-box')
        
        result = juwelier_exchange_scraper._parse_watch_element(element)
        
        assert result is None
    
    def test_image_srcset_parsing_priority(self, juwelier_exchange_scraper):
        """Test image srcset parsing with priority order."""
        test_cases = [
            # (srcset, expected_preference), in the shop's own file names
            ("/978973_1_400x400.webp 400w, /978973_1_800x800.webp 800w, /978973_1_1920x1920.webp 1920w", "1920x1920.webp"),
            ("/978973_1_400x400.webp 400w, /978973_1_800x800.jpg 800w", "400x400.webp"),  # Prefer webp
            ("", None),  # Empty srcset
            (" ", None),  # A srcset that names no picture
            (" , ,", None),
        ]
        
        for srcset, expected_preference in test_cases:
            srcset_attr = f'srcset="{srcset}"' if srcset else ''
            html = f"""
            <div class="card product-box" data-product-information='{{"id": 12345}}'>
                <a class="card-body-link" href="/uhren/test-watch">
                    <img class="product-image" 
                         src="/fallback.jpg"
                         {srcset_attr}
                         alt="Test" />
                    <span class="product-price">€ 1.000,00</span>
                </a>
            </div>
            """
            soup = BeautifulSoup(html, 'html.parser')
            element = soup.select_one('.card.product-box')
            
            watch = juwelier_exchange_scraper._parse_watch_element(element)
            
            assert watch is not None
            if expected_preference:
                assert expected_preference in watch.image_url
            else:
                # Should fallback to src
                assert "fallback.jpg" in watch.image_url

    def test_image_srcset_prefers_the_larger_jpg(self, juwelier_exchange_scraper):
        """Without a webp picture, the larger jpg of the srcset is taken."""
        html = """
        <div class="card product-box" data-product-information='{"id": 12345}'>
            <a class="card-body-link" href="/uhren/test-watch">
                <img class="product-image"
                     src="/fallback.jpg"
                     srcset="/978973_1_400x400.jpg 400w, /978973_1_800x800.jpg 800w"
                     alt="Test" />
                <span class="product-price">€ 1.000,00</span>
            </a>
        </div>
        """
        element = BeautifulSoup(html, 'html.parser').select_one('.card.product-box')

        watch = juwelier_exchange_scraper._parse_watch_element(element)

        assert "800x800.jpg" in watch.image_url

    @pytest.mark.asyncio
    async def test_extract_watch_details(self, juwelier_exchange_scraper, juwelier_exchange_detail_html):
        """Test detail extraction from the watch's own page."""
        watch = WatchData(
            title="Rolex Submariner Date Ref. 116610LN",
            brand="Rolex",
            url="https://juwelier-exchange.de/uhren/test",
            site_name="Juwelier Exchange",
            site_key="juwelier_exchange"
        )
        
        soup = BeautifulSoup(juwelier_exchange_detail_html, 'html.parser')
        
        await juwelier_exchange_scraper._extract_watch_details(watch, soup)
        
        # Check table data extraction
        assert watch.reference == "116610LN"
        assert watch.case_material == "Edelstahl"  # a fineness is prefixed only when it is a number
        
        # Check description parsing
        assert watch.year == "2020"
        assert watch.has_box is True
        assert watch.has_papers is True

    def test_model_before_a_reference(self, juwelier_exchange_scraper):
        """A name that ends in "Ref. <reference>" gives the model without it."""
        assert juwelier_exchange_scraper._model("Rolex Submariner Date Ref. 116610LN", "Rolex") == "Submariner"

    @pytest.mark.asyncio
    async def test_extract_watch_details_diameter_after_a_colon(self, juwelier_exchange_scraper, juwelier_exchange_detail_html):
        """A diameter written as "Gehäusedurchmesser: 40 mm" is read."""
        watch = WatchData(
            title="Unknown Watch",
            url="https://juwelier-exchange.de/uhren/test",
            site_name="Juwelier Exchange",
            site_key="juwelier_exchange"
        )

        soup = BeautifulSoup(juwelier_exchange_detail_html, 'html.parser')

        await juwelier_exchange_scraper._extract_watch_details(watch, soup)

        assert watch.diameter == "40 mm"

    @pytest.mark.asyncio
    async def test_extract_watch_details_from_a_minimal_page(self, juwelier_exchange_scraper, juwelier_exchange_minimal_detail_html):
        """Test detail extraction from a page with little on it."""
        watch = WatchData(
            title="Omega Speedmaster Professional",
            url="https://juwelier-exchange.de/uhren/test",
            site_name="Juwelier Exchange",
            site_key="juwelier_exchange"
        )
        
        soup = BeautifulSoup(juwelier_exchange_minimal_detail_html, 'html.parser')
        
        await juwelier_exchange_scraper._extract_watch_details(watch, soup)
        
        assert watch.reference == "311.30.42.30.01.005"
        assert watch.case_material == "Edelstahl"
        assert watch.year == "2019"
        assert watch.diameter == "42 mm"

    @pytest.mark.asyncio
    @pytest.mark.xfail(
        strict=True,
        reason="'Nur Uhr, keine Papiere oder Box vorhanden.' is read as box and papers present",
    )
    async def test_extract_watch_details_without_box_and_papers(self, juwelier_exchange_scraper, juwelier_exchange_minimal_detail_html):
        """A description saying there is neither box nor papers shows neither."""
        watch = WatchData(
            title="Unknown Watch",
            url="https://juwelier-exchange.de/uhren/test",
            site_name="Juwelier Exchange",
            site_key="juwelier_exchange"
        )
        
        soup = BeautifulSoup(juwelier_exchange_minimal_detail_html, 'html.parser')
        
        await juwelier_exchange_scraper._extract_watch_details(watch, soup)
        
        assert watch.has_box is False
        assert watch.has_papers is False

    @pytest.mark.asyncio
    async def test_extract_watch_details_material_mapping(self, juwelier_exchange_scraper, juwelier_exchange_complex_detail_html):
        """Test case material mapping from German terms."""
        watch = WatchData(
            title="Unknown Watch",
            url="https://juwelier-exchange.de/uhren/test",
            site_name="Juwelier Exchange",
            site_key="juwelier_exchange"
        )
        
        soup = BeautifulSoup(juwelier_exchange_complex_detail_html, 'html.parser')
        
        await juwelier_exchange_scraper._extract_watch_details(watch, soup)
        
        # Check material combination and mapping
        assert watch.case_material == "750 Weißgold"
        assert watch.year == "2018"
        assert watch.diameter == "37 mm"
        assert watch.has_box is True
        assert watch.has_papers is True

    @pytest.mark.asyncio
    async def test_diameter_extraction_patterns(self, juwelier_exchange_scraper):
        """Test diameter extraction from various German description patterns."""
        test_cases = [
            ("Durchmesser 40 mm", "40 mm"),
            ("Gehäusedurchmesser von 42 mm", "42 mm"),
            ("Gehäusegröße ca. 38,5 mm", "38.5 mm"),
            ("Gehäusedurchmesser: 40 mm", "40 mm"),
            ("20,5 x 28 mm rectangular case", "20.5 mm"),  # Rectangular, take first dimension
            ("No diameter mentioned", None),
        ]
        
        for description, expected_diameter in test_cases:
            watch = WatchData(
                title="Test Watch",
                url="https://juwelier-exchange.de/uhren/test",
                site_name="Juwelier Exchange",
                site_key="juwelier_exchange"
            )
            page = BeautifulSoup(
                '<div class="product-detail-description-text" itemprop="description">'
                f"<p>{description}</p></div>",
                "html.parser",
            )

            await juwelier_exchange_scraper._extract_watch_details(watch, page)

            assert watch.diameter == expected_diameter, f"Failed for description: {description}"
    
    def test_model_extraction_from_title(self, juwelier_exchange_scraper):
        """Test model extraction from complex titles."""
        test_cases = [
            # (title, brand, expected_model)
            ("Herrenuhr Rolex 'Submariner' Ref. 116610LN", "Rolex", "Submariner"),
            ("Damenuhr Patek Philippe 'Calatrava' 5196G", "Patek Philippe", "Calatrava"),
            ("Unisexuhr Omega Speedmaster Professional", "Omega", "Speedmaster Professional"),
            ("Rolex Submariner Date Automatik", "Rolex", "Submariner Date"),  # Remove function terms
            ("Omega 'Seamaster Planet Ocean' Chrono", "Omega", "Seamaster Planet Ocean"),
        ]
        
        for title, brand, expected_model in test_cases:
            model = juwelier_exchange_scraper._model(title, brand)

            assert model == expected_model, f"Failed for title: {title} with brand: {brand}"
    
    @pytest.mark.asyncio
    async def test_box_papers_detection(self, juwelier_exchange_scraper):
        """Test box and papers detection from German descriptions."""
        test_cases = [
            ("Originalbox, Garantiekarte, Bedienungsanleitung", True, True),
            ("Uhr, Box, Papiere, Zertifikat", True, True),
            ("Nur Papiere vorhanden", True, False),
            ("Nur Box verfügbar", False, True),
            ("Ohne Box und Papiere", False, False),
            ("Nur Uhr", False, False),
            ("No mention", None, None),
        ]
        
        for description, expected_papers, expected_box in test_cases:
            # Mock parse_box_papers function behavior
            with patch('scrapers.juwelier_exchange.parse_box_papers') as mock_parse:
                mock_parse.return_value = (expected_papers, expected_box)
                
                detail_html = f"""
                <div class="product-detail-description-text" itemprop="description">
                    <p>{description}</p>
                </div>
                """
                
                watch = WatchData(
                    title="Test Watch",
                    url="https://juwelier-exchange.de/uhren/test",
                    site_name="Juwelier Exchange",
                    site_key="juwelier_exchange"
                )
                
                soup = BeautifulSoup(detail_html, 'html.parser')
                await juwelier_exchange_scraper._extract_watch_details(watch, soup)
                
                assert watch.has_papers == expected_papers, f"Papers detection failed for: {description}"
                assert watch.has_box == expected_box, f"Box detection failed for: {description}"

    @pytest.mark.asyncio
    async def test_full_scrape_integration(self, juwelier_exchange_scraper, juwelier_exchange_listing_html):
        """Test full scraping workflow integration."""
        with patch('scrapers.base.fetch_page', return_value=juwelier_exchange_listing_html):
            with patch('scrapers.base.APP_CONFIG') as mock_config:
                mock_config.enable_detail_scraping = False
                
                watches = await juwelier_exchange_scraper.scrape()
        
        assert len(watches) == 4
        assert all(isinstance(watch, WatchData) for watch in watches)
        assert all(watch.site_key == "juwelier_exchange" for watch in watches)
        assert all(watch.site_name == "Juwelier Exchange" for watch in watches)
        assert all(watch.currency == "EUR" for watch in watches if watch.price)
        
        # Verify composite IDs are generated
        assert len(juwelier_exchange_scraper.seen_ids) == 4
        for watch in watches:
            assert watch.composite_id in juwelier_exchange_scraper.seen_ids
    
    @pytest.mark.asyncio
    async def test_scrape_with_seen_watches(self, juwelier_exchange_scraper, juwelier_exchange_listing_html):
        """Test scraping with some watches already seen."""
        # Create a seen watch with same composite ID as first watch in listing
        seen_watch = WatchData(
            title="Unknown Watch",
            url="https://juwelier-exchange.de/uhren/rolex-submariner-date-116610ln",
            site_name="Juwelier Exchange",
            site_key="juwelier_exchange",
            price=Decimal("8500.00"),
            currency="EUR"
        )
        juwelier_exchange_scraper.seen_ids = {seen_watch.composite_id}
        
        with patch('scrapers.base.fetch_page', return_value=juwelier_exchange_listing_html):
            with patch('scrapers.base.APP_CONFIG') as mock_config:
                mock_config.enable_detail_scraping = False
                
                watches = await juwelier_exchange_scraper.scrape()
        
        # Should return only new watches (3 instead of 4)
        assert len(watches) == 3
        assert not any("rolex-submariner-date-116610ln" in watch.url for watch in watches)
    
    @pytest.mark.asyncio
    async def test_scrape_parse_error_handling(self, juwelier_exchange_scraper):
        """Test scraping handles parse errors gracefully."""
        malformed_html = """
        <div class="card product-box" data-product-information='{"id": 12345}'>
            <a class="card-body-link" href="/uhren/error-watch">
                <img class="product-image" src="/images/test.jpg" alt="Error"/>
                <span class="product-price">€ 1.000,00</span>
            </a>
        </div>
        """
        
        with patch('scrapers.base.fetch_page', return_value=malformed_html):
            with patch('scrapers.base.APP_CONFIG') as mock_config:
                mock_config.enable_detail_scraping = False
                
                # Mock _parse_watch_element to raise an error
                original_parse = juwelier_exchange_scraper._parse_watch_element
                def mock_parse(element):
                    if "error-watch" in str(element):
                        raise Exception("Parse error")
                    return original_parse(element)
                
                juwelier_exchange_scraper._parse_watch_element = mock_parse
                
                watches = await juwelier_exchange_scraper.scrape()
        
        # Should handle errors gracefully and return empty list
        assert watches == []
    
    def test_composite_id_generation(self, juwelier_exchange_scraper):
        """Test that watches generate unique composite IDs."""
        html_template = """
        <div class="card product-box" data-product-information='{{"id": {id}}}'>
            <a class="card-body-link" href="/uhren/{url_path}">
                <img class="product-image" src="/images/{id}.jpg" alt="Watch {id}"/>
                <span class="product-price">€ 1.000,00</span>
            </a>
        </div>
        """
        
        html1 = html_template.format(id=12345, url_path="watch-1")
        html2 = html_template.format(id=12346, url_path="watch-2")
        
        soup1 = BeautifulSoup(html1, 'html.parser')
        soup2 = BeautifulSoup(html2, 'html.parser')
        
        watch1 = juwelier_exchange_scraper._parse_watch_element(soup1.select_one('.card.product-box'))
        watch2 = juwelier_exchange_scraper._parse_watch_element(soup2.select_one('.card.product-box'))
        
        assert watch1 is not None
        assert watch2 is not None
        assert watch1.composite_id != watch2.composite_id
        assert watch1.composite_id is not None
        assert watch2.composite_id is not None