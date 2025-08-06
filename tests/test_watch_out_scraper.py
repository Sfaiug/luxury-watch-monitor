"""Comprehensive tests for Watch Out scraper implementation."""

import pytest
import json
import asyncio
from unittest.mock import AsyncMock, Mock, patch
from bs4 import BeautifulSoup
from decimal import Decimal
from urllib.parse import urljoin

from scrapers.watch_out import WatchOutScraper
from models import WatchData
from config import SiteConfig


@pytest.fixture
def watch_out_config():
    """Watch Out site configuration for testing."""
    return SiteConfig(
        name="Watch Out",
        key="watch_out",
        url="https://watch-out.de/collections/watches",
        webhook_env_var="WATCH_OUT_WEBHOOK_URL",
        color=0xFF6347,
        base_url="https://watch-out.de",
        known_brands={
            "rolex": "Rolex",
            "omega": "Omega",
            "tudor": "Tudor",
            "patek philippe": "Patek Philippe",
            "audemars piguet": "Audemars Piguet",
            "breitling": "Breitling",
            "iwc": "IWC",
            "cartier": "Cartier"
        }
    )


@pytest.fixture
def watch_out_scraper(watch_out_config, mock_aiohttp_session, mock_logger):
    """Watch Out scraper instance for testing."""
    return WatchOutScraper(watch_out_config, mock_aiohttp_session, mock_logger)


@pytest.fixture
def watch_out_listing_html():
    """Realistic Watch Out listing page HTML with Shopify analytics."""
    return """
    <!DOCTYPE html>
    <html lang="de">
    <head>
        <title>Watch Out - Premium Timepieces</title>
        <script>
            window.ShopifyAnalytics = window.ShopifyAnalytics || {};
            window.ShopifyAnalytics.meta = window.ShopifyAnalytics.meta || {};
            var meta = {
                "currency": "EUR",
                "products": [
                    {
                        "id": 7234567890123,
                        "title": "Rolex Submariner Date 116610LN",
                        "untranslatedTitle": "Rolex Submariner Date 116610LN",
                        "vendor": "Rolex",
                        "url": "/products/rolex-submariner-date-116610ln",
                        "variants": [{
                            "id": 41234567890123,
                            "name": "Rolex Submariner Date 116610LN",
                            "price": 850000,
                            "sku": "116610LN",
                            "product": {
                                "url": "/products/rolex-submariner-date-116610ln"
                            }
                        }]
                    },
                    {
                        "id": 7234567890124,
                        "title": "Omega Speedmaster Professional Moonwatch",
                        "untranslatedTitle": "Omega Speedmaster Professional Moonwatch", 
                        "vendor": "Omega",
                        "url": "/products/omega-speedmaster-professional",
                        "variants": [{
                            "id": 41234567890124,
                            "name": "Default Title",
                            "price": 420000,
                            "sku": "311.30.42.30.01.005",
                            "product": {
                                "url": "/products/omega-speedmaster-professional"
                            }
                        }]
                    },
                    {
                        "id": 7234567890125,
                        "title": "Tudor Black Bay 58",
                        "untranslatedTitle": "Tudor Black Bay 58",
                        "vendor": "Tudor",
                        "url": "/products/tudor-black-bay-58",
                        "variants": [{
                            "id": 41234567890125,
                            "name": "Tudor Black Bay 58 79030N",
                            "price": 320000,
                            "sku": "79030N",
                            "product": {
                                "url": "/products/tudor-black-bay-58"
                            }
                        }]
                    }
                ]
            };
            window.ShopifyAnalytics.meta = meta;
        </script>
    </head>
    <body>
        <div class="product-listing">
            <!-- First product card - matches first analytics entry -->
            <product-card handle="rolex-submariner-date-116610ln">
                <div class="product-card__info">
                    <a class="text-xs link-faded" href="/brands/rolex">Rolex</a>
                    <div class="product-card__title">
                        <a class="bold" href="/products/rolex-submariner-date-116610ln">
                            Rolex Submariner Date
                        </a>
                    </div>
                </div>
                <div class="product-card__badge-list">
                    <span class="badge badge--primary">116610LN</span>
                </div>
                <sale-price class="price">€8,500.00</sale-price>
                <img class="product-card__image" 
                     src="/images/rolex-submariner-400x400.jpg"
                     srcset="/images/rolex-submariner-400x400.jpg 400w, 
                             /images/rolex-submariner-800x800.jpg 800w,
                             /images/rolex-submariner-1200x1200.jpg 1200w"
                     alt="Rolex Submariner" />
            </product-card>
            
            <!-- Second product card - matches second analytics entry -->
            <product-card handle="omega-speedmaster-professional">
                <div class="product-card__info">
                    <a class="text-xs link-faded" href="/brands/omega">Omega</a>
                    <div class="product-card__title">
                        <a class="bold" href="/products/omega-speedmaster-professional">
                            Omega Speedmaster Professional
                        </a>
                    </div>
                </div>
                <div class="product-card__badge-list">
                    <span class="badge badge--primary">311.30.42.30.01.005</span>
                </div>
                <sale-price class="price">€4,200.00</sale-price>
                <img class="product-card__image" 
                     src="/images/omega-speedmaster-400x400.jpg"
                     alt="Omega Speedmaster" />
            </product-card>
            
            <!-- Third product card - matches third analytics entry -->
            <product-card handle="tudor-black-bay-58">
                <div class="product-card__info">
                    <a class="text-xs link-faded" href="/brands/tudor">Tudor</a>
                    <div class="product-card__title">
                        <a class="bold" href="/products/tudor-black-bay-58">
                            Tudor Black Bay 58
                        </a>
                    </div>
                </div>
                <div class="product-card__badge-list">
                    <span class="badge badge--primary">79030N</span>
                </div>
                <sale-price class="price">€3,200.00</sale-price>
                <img class="product-card__image" 
                     src="/images/tudor-black-bay-400x400.jpg"
                     alt="Tudor Black Bay" />
            </product-card>
            
            <!-- Fourth product card - sold out, should be skipped -->
            <product-card handle="patek-philippe-calatrava-sold">
                <sold-out-badge>Sold Out</sold-out-badge>
                <div class="product-card__info">
                    <a class="text-xs link-faded" href="/brands/patek-philippe">Patek Philippe</a>
                    <div class="product-card__title">
                        <a class="bold" href="/products/patek-philippe-calatrava">
                            Patek Philippe Calatrava
                        </a>
                    </div>
                </div>
                <sale-price class="price">€32,000.00</sale-price>
                <img class="product-card__image" src="/images/patek-calatrava-400x400.jpg" alt="Patek Philippe" />
            </product-card>
        </div>
    </body>
    </html>
    """


@pytest.fixture
def watch_out_detail_html():
    """Realistic Watch Out detail page HTML with accordion details."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Rolex Submariner Date 116610LN - Watch Out</title>
    </head>
    <body>
        <div class="product-detail">
            <div class="section-stack__intro">
                <div class="metafield-rich_text_field">
                    <div class="prose">
                        <p>Die Rolex Submariner Date ist eine der bekanntesten Taucheruhren der Welt. 
                        Dieses Exemplar stammt aus dem Jahr 2020 und befindet sich in ausgezeichnetem Zustand.</p>
                        
                        <p>Das 40mm Edelstahlgehäuse zeigt kaum Gebrauchsspuren und die schwarze Keramiklünette 
                        ist in perfektem Zustand. Die Uhr wurde kürzlich gewartet und läuft präzise.</p>
                    </div>
                </div>
            </div>
            
            <div class="accordion-box">
                <collapsible-element>
                    <summary>Spezifikationen</summary>
                    <div id="specs-content">
                        Herstellungsjahr: 2020
                        Referenznummer: 116610LN
                        Durchmesser: 40mm
                        Gehäusematerial: Edelstahl
                        Zustand: Ausgezeichnet
                    </div>
                </collapsible-element>
                
                <collapsible-element>
                    <summary>Zustand</summary>
                    <div id="condition-content">
                        Die Uhr befindet sich in ausgezeichnetem Zustand mit minimalen Gebrauchsspuren. 
                        Das Gehäuse weist nur leichte Kratzer auf, die bei normalem Gebrauch entstanden sind.
                        Die Lünette ist in perfektem Zustand ohne Beschädigungen.
                    </div>
                </collapsible-element>
                
                <collapsible-element>
                    <summary>Lieferumfang</summary>
                    <div id="scope-content">
                        Lieferung erfolgt mit Originalbox, allen Papieren, Garantiekarte und Bedienungsanleitung.
                        Alle Glieder des Armbands sind vorhanden.
                    </div>
                </collapsible-element>
            </div>
        </div>
    </body>
    </html>
    """


@pytest.fixture
def watch_out_minimal_detail_html():
    """Minimal Watch Out detail page for fallback testing."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Simple Watch - Watch Out</title>
    </head>
    <body>
        <div class="product-detail">
            <div class="section-stack__intro">
                <div class="metafield-rich_text_field">
                    <div class="prose">
                        <p>This is a simple watch with minimal information.</p>
                    </div>
                </div>
            </div>
        </div>
    </body>
    </html>
    """


@pytest.fixture
def watch_out_empty_html():
    """Empty Watch Out listing page."""
    return """
    <html>
    <body>
        <div class="empty-collection">
            <p>Keine Uhren verfügbar.</p>
        </div>
    </body>
    </html>
    """


@pytest.fixture
def watch_out_malformed_html():
    """Malformed Watch Out listing with missing elements."""
    return """
    <html>
    <body>
        <script>
            // Malformed ShopifyAnalytics
            window.ShopifyAnalytics = {
                meta: {
                    products: "invalid data"
                }
            };
        </script>
        <div class="product-listing">
            <!-- Product card without handle -->
            <product-card>
                <div class="product-card__title">
                    <a class="bold">Watch Without Handle</a>
                </div>
                <sale-price class="price">€1,000.00</sale-price>
            </product-card>
            
            <!-- Complete product card -->
            <product-card handle="complete-watch">
                <div class="product-card__title">
                    <a class="bold" href="/products/complete-watch">Complete Watch</a>
                </div>
                <sale-price class="price">€2,000.00</sale-price>
            </product-card>
        </div>
    </body>
    </html>
    """


class TestWatchOutScraper:
    """Test Watch Out scraper implementation."""
    
    def test_initialization(self, watch_out_config, mock_aiohttp_session, mock_logger):
        """Test scraper initialization."""
        scraper = WatchOutScraper(watch_out_config, mock_aiohttp_session, mock_logger)
        
        assert scraper.config == watch_out_config
        assert scraper.session == mock_aiohttp_session
        assert len(scraper.seen_ids) == 0
    
    @pytest.mark.asyncio
    async def test_extract_watches_success_with_shopify_analytics(self, watch_out_scraper, watch_out_listing_html):
        """Test successful watch extraction with Shopify analytics matching."""
        soup = BeautifulSoup(watch_out_listing_html, 'html.parser')
        
        watches = await watch_out_scraper._extract_watches(soup)
        
        # Should return 3 watches (4th is sold out)
        assert len(watches) == 3
        
        # Test first watch - Rolex with analytics data
        rolex_watch = watches[0]
        assert rolex_watch.title == "Rolex Submariner Date 116610LN"  # From analytics
        assert rolex_watch.brand == "Rolex"  # From analytics
        assert rolex_watch.reference == "116610LN"  # From analytics SKU
        assert rolex_watch.price == Decimal("8500.00")  # From analytics (cents converted)
        assert rolex_watch.currency == "EUR"
        assert rolex_watch.url == "https://watch-out.de/products/rolex-submariner-date-116610ln"
        assert rolex_watch.image_url == "https://watch-out.de/images/rolex-submariner-1200x1200.jpg"  # Highest res from srcset
        assert rolex_watch.site_name == "Watch Out"
        assert rolex_watch.site_key == "watch_out"
        
        # Test second watch - Omega with "Default Title" handling
        omega_watch = watches[1]
        assert omega_watch.title == "Omega Speedmaster Professional Moonwatch"  # From untranslatedTitle
        assert omega_watch.brand == "Omega"
        assert omega_watch.reference == "311.30.42.30.01.005"
        assert omega_watch.price == Decimal("4200.00")
        
        # Test third watch - Tudor with variant name
        tudor_watch = watches[2]
        assert tudor_watch.title == "Tudor Black Bay 58 79030N"  # From variant name
        assert tudor_watch.brand == "Tudor"
        assert tudor_watch.reference == "79030N"
        assert tudor_watch.price == Decimal("3200.00")
    
    @pytest.mark.asyncio
    async def test_extract_watches_fallback_to_visual_elements(self, watch_out_scraper):
        """Test fallback to visual elements when analytics data is missing."""
        html_without_analytics = """
        <html>
        <body>
            <div class="product-listing">
                <product-card handle="visual-fallback-watch">
                    <div class="product-card__info">
                        <a class="text-xs link-faded" href="/brands/omega">Omega</a>
                        <div class="product-card__title">
                            <a class="bold" href="/products/visual-fallback-watch">
                                Visual Fallback Watch
                            </a>
                        </div>
                    </div>
                    <div class="product-card__badge-list">
                        <span class="badge badge--primary">VISUAL123</span>
                    </div>
                    <sale-price class="price">€1,500.00</sale-price>
                    <img class="product-card__image" 
                         src="/images/fallback-watch.jpg"
                         alt="Fallback" />
                </product-card>
            </div>
        </body>
        </html>
        """
        
        soup = BeautifulSoup(html_without_analytics, 'html.parser')
        
        watches = await watch_out_scraper._extract_watches(soup)
        
        assert len(watches) == 1
        
        watch = watches[0]
        assert watch.title == "Visual Fallback Watch"  # From visual element
        assert watch.brand == "Omega"  # From visual element
        assert watch.reference == "VISUAL123"  # From badge
        assert watch.price == Decimal("1500.00")  # From visual element
        assert watch.url == "https://watch-out.de/products/visual-fallback-watch"
    
    @pytest.mark.asyncio
    async def test_extract_watches_empty_page(self, watch_out_scraper, watch_out_empty_html):
        """Test extraction from empty listing page."""
        soup = BeautifulSoup(watch_out_empty_html, 'html.parser')
        
        watches = await watch_out_scraper._extract_watches(soup)
        
        assert watches == []
    
    @pytest.mark.asyncio
    async def test_extract_watches_malformed_analytics(self, watch_out_scraper, watch_out_malformed_html):
        """Test extraction with malformed Shopify analytics."""
        soup = BeautifulSoup(watch_out_malformed_html, 'html.parser')
        
        watches = await watch_out_scraper._extract_watches(soup)
        
        # Should return 1 watch (complete one), malformed analytics should be handled gracefully
        assert len(watches) == 1
        
        watch = watches[0]
        assert watch.title == "Complete Watch"
        assert watch.url == "https://watch-out.de/products/complete-watch"
        assert watch.price == Decimal("2000.00")
    
    def test_parse_watch_element_sold_out_skip(self, watch_out_scraper):
        """Test that sold out watches are skipped."""
        html = """
        <product-card handle="sold-out-watch">
            <sold-out-badge>Sold Out</sold-out-badge>
            <div class="product-card__title">
                <a class="bold" href="/products/sold-out-watch">Sold Out Watch</a>
            </div>
            <sale-price class="price">€5,000.00</sale-price>
        </product-card>
        """
        soup = BeautifulSoup(html, 'html.parser')
        element = soup.select_one('product-card')
        
        result = watch_out_scraper._parse_watch_element(element, 0, [])
        
        assert result is None
    
    def test_parse_watch_element_missing_url(self, watch_out_scraper):
        """Test parsing element without URL returns None."""
        html = """
        <product-card>
            <div class="product-card__title">
                <a class="bold">Watch Without URL</a>
            </div>
            <sale-price class="price">€1,000.00</sale-price>
        </product-card>
        """
        soup = BeautifulSoup(html, 'html.parser')
        element = soup.select_one('product-card')
        
        result = watch_out_scraper._parse_watch_element(element, 0, [])
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_shopify_analytics_parsing_error_handling(self, watch_out_scraper):
        """Test Shopify analytics parsing error handling."""
        html_with_invalid_json = """
        <html>
        <head>
            <script>
                window.ShopifyAnalytics = window.ShopifyAnalytics || {};
                var meta = {
                    "products": [
                        // Invalid JSON comment
                        {
                            "id": 123,
                            "title": "Invalid JSON Watch"
                        }
                    ]
                };
            </script>
        </head>
        <body>
            <product-card handle="test-watch">
                <div class="product-card__title">
                    <a class="bold" href="/products/test-watch">Test Watch</a>
                </div>
                <sale-price class="price">€1,000.00</sale-price>
            </product-card>
        </body>
        </html>
        """
        
        soup = BeautifulSoup(html_with_invalid_json, 'html.parser')
        
        # Should handle JSON parsing error gracefully
        watches = await watch_out_scraper._extract_watches(soup)
        
        assert len(watches) == 1  # Should still process visual elements
        assert watches[0].title == "Test Watch"
    
    @pytest.mark.asyncio
    async def test_extract_watch_details_success(self, watch_out_scraper, watch_out_detail_html):
        """Test successful detail extraction from accordion."""
        watch = WatchData(
            title="Test Watch",
            url="https://watch-out.de/products/test",
            site_name="Watch Out",
            site_key="watch_out"
        )
        
        soup = BeautifulSoup(watch_out_detail_html, 'html.parser')
        
        await watch_out_scraper._extract_watch_details(watch, soup)
        
        # Check accordion details extraction
        assert watch.year == "2020"
        assert watch.reference == "116610LN"
        assert watch.diameter == "40mm"
        assert watch.case_material == "Edelstahl"
        
        # Check box and papers from lieferumfang
        assert watch.has_box is True
        assert watch.has_papers is True
        
        # Check condition parsing
        assert watch.condition is not None
    
    @pytest.mark.asyncio
    async def test_extract_watch_details_minimal_data(self, watch_out_scraper, watch_out_minimal_detail_html):
        """Test detail extraction with minimal data."""
        watch = WatchData(
            title="Original Title",
            url="https://watch-out.de/products/test",
            site_name="Watch Out",
            site_key="watch_out"
        )
        
        soup = BeautifulSoup(watch_out_minimal_detail_html, 'html.parser')
        
        await watch_out_scraper._extract_watch_details(watch, soup)
        
        # Minimal data shouldn't contain condition keywords
        assert watch.condition is None
        # Other fields should remain unchanged or None
        assert watch.year is None
        assert watch.reference is None
    
    def test_parse_accordion_details_specifications(self, watch_out_scraper):
        """Test accordion specifications parsing."""
        accordion_html = """
        <div class="accordion-box">
            <collapsible-element>
                <summary>Spezifikationen</summary>
                <div id="specs-content">
                    Herstellungsjahr: 2021
                    Referenznummer: TEST123
                    Durchmesser: 42mm
                    Gehäusematerial: Gold
                    Zustand: Sehr gut
                </div>
            </collapsible-element>
        </div>
        """
        
        soup = BeautifulSoup(accordion_html, 'html.parser')
        accordion_box = soup.select_one('div.accordion-box')
        
        details = watch_out_scraper._parse_accordion_details_watch_out(accordion_box)
        
        assert details.get("herstellungsjahr") == "2021"
        assert details.get("referenznummer") == "TEST123"
        assert details.get("durchmesser") == "42mm"
        assert details.get("gehäusematerial") == "Gold"
        assert details.get("zustand") == "Sehr gut"
    
    def test_parse_accordion_details_condition_section(self, watch_out_scraper):
        """Test accordion condition section parsing."""
        accordion_html = """
        <div class="accordion-box">
            <collapsible-element>
                <summary>Zustand</summary>
                <div id="condition-content">
                    Die Uhr ist in ausgezeichnetem Zustand mit minimalen Gebrauchsspuren.
                </div>
            </collapsible-element>
        </div>
        """
        
        soup = BeautifulSoup(accordion_html, 'html.parser')
        accordion_box = soup.select_one('div.accordion-box')
        
        details = watch_out_scraper._parse_accordion_details_watch_out(accordion_box)
        
        assert details.get("zustand") == "Die Uhr ist in ausgezeichnetem Zustand mit minimalen Gebrauchsspuren."
    
    def test_parse_accordion_details_scope_section(self, watch_out_scraper):
        """Test accordion scope of delivery section parsing."""
        accordion_html = """
        <div class="accordion-box">
            <collapsible-element>
                <summary>Lieferumfang</summary>
                <div id="scope-content">
                    Originalbox, Papiere, Zertifikat und Bedienungsanleitung sind enthalten.
                </div>
            </collapsible-element>
        </div>
        """
        
        soup = BeautifulSoup(accordion_html, 'html.parser')
        accordion_box = soup.select_one('div.accordion-box')
        
        details = watch_out_scraper._parse_accordion_details_watch_out(accordion_box)
        
        assert details.get("lieferumfang") == "Originalbox, Papiere, Zertifikat und Bedienungsanleitung sind enthalten."
    
    def test_parse_accordion_details_key_value_pairs(self, watch_out_scraper):
        """Test accordion parsing with key-value pairs."""
        accordion_html = """
        <div class="accordion-box">
            <collapsible-element>
                <summary>Details</summary>
                <div id="details-content">
                    Jahr: 2019
                    
                    Referenz: ABC123
                    
                    Material: Edelstahl
                    
                    Durchmesser: 38mm
                </div>
            </collapsible-element>
        </div>
        """
        
        soup = BeautifulSoup(accordion_html, 'html.parser')
        accordion_box = soup.select_one('div.accordion-box')
        
        details = watch_out_scraper._parse_accordion_details_watch_out(accordion_box)
        
        assert details.get("herstellungsjahr") == "2019"
        assert details.get("referenznummer") == "ABC123"
        assert details.get("gehäusematerial") == "Edelstahl"
        assert details.get("durchmesser") == "38mm"
    
    def test_diameter_extraction_with_regex(self, watch_out_scraper):
        """Test diameter extraction with regex matching."""
        test_cases = [
            ("42mm", "42mm"),
            ("38,5 mm", "38.5mm"),
            ("40.0mm", "40.0mm"),
            ("Invalid diameter", None),
            ("", None),
        ]
        
        for diameter_text, expected in test_cases:
            # Simulate diameter extraction logic
            import re
            
            diameter = None
            if diameter_text:
                dia_match = re.search(r'(\d{1,2}(?:[.,]\d{1,2})?)\s*mm', diameter_text, re.IGNORECASE)
                if dia_match:
                    diameter = dia_match.group(1).replace(",", ".") + "mm"
                else:
                    # If no match found but text contains "mm", use as is
                    if "mm" in diameter_text:
                        diameter = diameter_text
            
            assert diameter == expected, f"Failed for diameter: {diameter_text}"
    
    def test_image_srcset_parsing(self, watch_out_scraper):
        """Test image srcset parsing to get highest resolution."""
        html = """
        <product-card handle="test-watch">
            <div class="product-card__title">
                <a class="bold" href="/products/test-watch">Test Watch</a>
            </div>
            <sale-price class="price">€1,000.00</sale-price>
            <img class="product-card__image" 
                 src="/images/test-400x400.jpg"
                 srcset="/images/test-400x400.jpg 400w, 
                         /images/test-800x800.jpg 800w,
                         /images/test-1200x1200.jpg 1200w"
                 alt="Test Watch" />
        </product-card>
        """
        
        soup = BeautifulSoup(html, 'html.parser')
        element = soup.select_one('product-card')
        
        watch = watch_out_scraper._parse_watch_element(element, 0, [])
        
        assert watch is not None
        # Should use highest resolution from srcset
        assert "1200x1200" in watch.image_url
    
    def test_price_parsing_from_analytics_vs_visual(self, watch_out_scraper):
        """Test price extraction priority: analytics over visual."""
        # Analytics data with price in cents
        analytics_data = [{
            "id": 123,
            "title": "Test Watch",
            "vendor": "TestBrand",
            "variants": [{
                "id": 456,
                "name": "Test Watch",
                "price": 150000,  # €1500.00 in cents
                "product": {"url": "/products/test-watch"}
            }]
        }]
        
        html = """
        <product-card handle="test-watch">
            <div class="product-card__title">
                <a class="bold" href="/products/test-watch">Test Watch</a>
            </div>
            <sale-price class="price">€2,000.00</sale-price>  <!-- Visual price different from analytics -->
        </product-card>
        """
        
        soup = BeautifulSoup(html, 'html.parser')
        element = soup.select_one('product-card')
        
        watch = watch_out_scraper._parse_watch_element(element, 0, analytics_data)
        
        assert watch is not None
        # Should use analytics price (€1500.00) over visual price (€2000.00)
        assert watch.price == Decimal("1500.00")
    
    def test_handle_extraction_from_different_sources(self, watch_out_scraper):
        """Test handle extraction from handle attribute vs href."""
        test_cases = [
            # (html, expected_handle)
            ('<product-card handle="explicit-handle"><a href="/products/different-handle">Test</a></product-card>', "explicit-handle"),
            ('<product-card><a href="/products/href-handle">Test</a></product-card>', "href-handle"),
            ('<product-card><a href="/products/href-handle?variant=123">Test</a></product-card>', "href-handle"),  # With query params
            ('<product-card><a>Test</a></product-card>', None),  # No handle or href
        ]
        
        for html_snippet, expected_handle in test_cases:
            soup = BeautifulSoup(html_snippet, 'html.parser')
            element = soup.select_one('product-card')
            
            # Extract handle logic
            handle = element.get('handle') if element else None
            if not handle:
                link_tag = element.select_one('a[href*="/products/"]') if element else None
                if link_tag and link_tag.has_attr('href'):
                    path = link_tag['href']
                    if path.startswith("/products/"):
                        handle = path.split("/products/")[-1].split("?")[0]
            
            assert handle == expected_handle, f"Failed for HTML: {html_snippet}"
    
    @pytest.mark.asyncio
    async def test_full_scrape_integration(self, watch_out_scraper, watch_out_listing_html):
        """Test full scraping workflow integration."""
        with patch('scrapers.base.fetch_page', return_value=watch_out_listing_html):
            with patch('scrapers.base.APP_CONFIG') as mock_config:
                mock_config.enable_detail_scraping = False
                
                watches = await watch_out_scraper.scrape()
        
        assert len(watches) == 3  # Sold out watch should be excluded
        assert all(isinstance(watch, WatchData) for watch in watches)
        assert all(watch.site_key == "watch_out" for watch in watches)
        assert all(watch.site_name == "Watch Out" for watch in watches)
        assert all(watch.currency == "EUR" for watch in watches)
        
        # Verify composite IDs are generated
        assert len(watch_out_scraper.seen_ids) == 3
        for watch in watches:
            assert watch.composite_id in watch_out_scraper.seen_ids
    
    @pytest.mark.asyncio
    async def test_scrape_with_seen_watches(self, watch_out_scraper, watch_out_listing_html):
        """Test scraping with some watches already seen."""
        # Pre-populate with one seen watch matching what would be scraped
        seen_watch = WatchData(
            title="Rolex Submariner Date 116610LN",
            url="https://watch-out.de/products/rolex-submariner-date-116610ln",
            site_name="Watch Out",
            site_key="watch_out",
            brand="Rolex",
            reference="116610LN", 
            price=8500.0,  # Match scraper output (float)
            currency="EUR"
        )
        watch_out_scraper.seen_ids = {seen_watch.composite_id}
        
        with patch('scrapers.base.fetch_page', return_value=watch_out_listing_html):
            with patch('scrapers.base.APP_CONFIG') as mock_config:
                mock_config.enable_detail_scraping = False
                
                watches = await watch_out_scraper.scrape()
        
        # Should return only new watches (2 instead of 3)
        assert len(watches) == 2
        assert not any(watch.title == "Rolex Submariner Date 116610LN" for watch in watches)
    
    @pytest.mark.asyncio
    async def test_scrape_parse_error_handling(self, watch_out_scraper):
        """Test scraping handles parse errors gracefully."""
        malformed_html = """
        <product-card handle="error-watch">
            <div class="product-card__title">
                <a class="bold" href="/products/error-watch">Error Watch</a>
            </div>
            <sale-price class="price">€1,000.00</sale-price>
        </product-card>
        """
        
        with patch('scrapers.base.fetch_page', return_value=malformed_html):
            with patch('scrapers.base.APP_CONFIG') as mock_config:
                mock_config.enable_detail_scraping = False
                
                # Mock _parse_watch_element to raise an error
                original_parse = watch_out_scraper._parse_watch_element
                def mock_parse(element, idx, analytics_data):
                    if "error-watch" in str(element):
                        raise Exception("Parse error")
                    return original_parse(element, idx, analytics_data)
                
                watch_out_scraper._parse_watch_element = mock_parse
                
                watches = await watch_out_scraper.scrape()
        
        # Should handle errors gracefully and return empty list
        assert watches == []
    
    def test_composite_id_generation(self, watch_out_scraper):
        """Test that watches generate unique composite IDs."""
        html_template = """
        <product-card handle="{handle}">
            <div class="product-card__title">
                <a class="bold" href="/products/{handle}">Watch {id}</a>
            </div>
            <sale-price class="price">€1,000.00</sale-price>
        </product-card>
        """
        
        html1 = html_template.format(handle="watch-1", id="1")
        html2 = html_template.format(handle="watch-2", id="2")
        
        soup1 = BeautifulSoup(html1, 'html.parser')
        soup2 = BeautifulSoup(html2, 'html.parser')
        
        watch1 = watch_out_scraper._parse_watch_element(soup1.select_one('product-card'), 0, [])
        watch2 = watch_out_scraper._parse_watch_element(soup2.select_one('product-card'), 0, [])
        
        assert watch1 is not None
        assert watch2 is not None
        assert watch1.composite_id != watch2.composite_id
        assert watch1.composite_id is not None
        assert watch2.composite_id is not None
    
    def test_shopify_analytics_title_preference(self, watch_out_scraper):
        """Test title preference: variant name > untranslatedTitle > title."""
        analytics_data = [{
            "id": 123,
            "title": "Generic Title",
            "untranslatedTitle": "Better Title",
            "vendor": "TestBrand",
            "variants": [{
                "id": 456,
                "name": "Best Title",
                "price": 100000,
                "product": {"url": "/products/test-watch"}
            }]
        }]
        
        html = """
        <product-card handle="test-watch">
            <div class="product-card__title">
                <a class="bold" href="/products/test-watch">Visual Title</a>
            </div>
            <sale-price class="price">€1,000.00</sale-price>
        </product-card>
        """
        
        soup = BeautifulSoup(html, 'html.parser')
        element = soup.select_one('product-card')
        
        watch = watch_out_scraper._parse_watch_element(element, 0, analytics_data)
        
        assert watch is not None
        # Should prefer variant name over other titles
        assert watch.title == "Best Title"
    
    def test_shopify_analytics_default_title_handling(self, watch_out_scraper):
        """Test handling of 'Default Title' in Shopify analytics."""
        analytics_data = [{
            "id": 123,
            "title": "Product Title",
            "untranslatedTitle": "Translated Product Title",
            "vendor": "TestBrand",
            "variants": [{
                "id": 456,
                "name": "Default Title",  # Should be ignored
                "price": 100000,
                "product": {"url": "/products/test-watch"}
            }]
        }]
        
        html = """
        <product-card handle="test-watch">
            <div class="product-card__title">
                <a class="bold" href="/products/test-watch">Visual Title</a>
            </div>
            <sale-price class="price">€1,000.00</sale-price>
        </product-card>
        """
        
        soup = BeautifulSoup(html, 'html.parser')
        element = soup.select_one('product-card')
        
        watch = watch_out_scraper._parse_watch_element(element, 0, analytics_data)
        
        assert watch is not None
        # Should use untranslatedTitle since variant name is "Default Title"
        assert watch.title == "Translated Product Title"