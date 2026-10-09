"""Tests for utility functions."""

import pytest
import asyncio
import time
import json
import aiohttp
from decimal import Decimal, InvalidOperation
from unittest.mock import AsyncMock, Mock, patch
from bs4 import BeautifulSoup

from utils import (
    clear_exchange_rate_cache,
    retry_with_backoff, fetch_page, get_usd_to_eur_rate, parse_price,
    parse_year, parse_box_papers, parse_condition, extract_text_from_element,
    parse_table_data
)


class TestRetryWithBackoff:
    """Test retry mechanism with exponential backoff."""
    
    @pytest.mark.asyncio
    async def test_retry_success_on_first_attempt(self):
        """Test successful function on first attempt."""
        call_count = 0
        
        async def successful_function():
            nonlocal call_count
            call_count += 1
            return "success"
        
        result = await retry_with_backoff(successful_function, max_retries=3)
        assert result == "success"
        assert call_count == 1
    
    @pytest.mark.asyncio
    async def test_retry_eventual_success(self):
        """Test function that succeeds after retries."""
        call_count = 0
        
        async def eventually_successful():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("Temporary failure")
            return "success"
        
        result = await retry_with_backoff(
            eventually_successful, 
            max_retries=3, 
            backoff_factor=1.1  # Faster for testing
        )
        assert result == "success"
        assert call_count == 3
    
    @pytest.mark.asyncio
    async def test_retry_final_failure(self):
        """Test function that always fails."""
        call_count = 0
        
        async def always_failing():
            nonlocal call_count
            call_count += 1
            raise ValueError("Always fails")
        
        with pytest.raises(ValueError, match="Always fails"):
            await retry_with_backoff(
                always_failing, 
                max_retries=2, 
                backoff_factor=1.1
            )
        
        assert call_count == 3  # Initial + 2 retries
    
    @pytest.mark.asyncio
    async def test_retry_specific_exceptions(self):
        """Test retry with specific exception types."""
        call_count = 0
        
        async def mixed_exceptions():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise aiohttp.ClientError("Network error")
            elif call_count == 2:
                raise ValueError("Different error")  # Should not be caught
            return "success"
        
        with pytest.raises(ValueError):
            await retry_with_backoff(
                mixed_exceptions, 
                max_retries=3,
                exceptions=(aiohttp.ClientError,)
            )
        
        assert call_count == 2


class TestFetchPage:
    """Test web page fetching functionality."""
    
    @pytest.mark.asyncio
    async def test_fetch_page_success(self, mock_aiohttp_session):
        """Test successful page fetch."""
        mock_aiohttp_session.get.return_value.__aenter__.return_value.text.return_value = "<html>Test</html>"
        
        result = await fetch_page(mock_aiohttp_session, "https://example.com")
        
        assert result == "<html>Test</html>"
        mock_aiohttp_session.get.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_fetch_page_with_logger(self, mock_aiohttp_session, mock_logger):
        """Test page fetch with logger."""
        mock_aiohttp_session.get.return_value.__aenter__.return_value.text.return_value = "<html>Test</html>"
        
        result = await fetch_page(mock_aiohttp_session, "https://example.com", mock_logger)
        
        assert result == "<html>Test</html>"
        # Logger should not have error calls for successful request
        mock_logger.error.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_fetch_page_network_error(self, mock_aiohttp_session, mock_logger):
        """Test page fetch with network error."""
        mock_aiohttp_session.get.side_effect = aiohttp.ClientError("Network error")
        
        result = await fetch_page(mock_aiohttp_session, "https://example.com", mock_logger)
        
        assert result is None
        mock_logger.error.assert_called()
    
    @pytest.mark.asyncio
    async def test_fetch_page_timeout(self, mock_aiohttp_session, mock_logger):
        """Test page fetch with timeout."""
        mock_aiohttp_session.get.side_effect = asyncio.TimeoutError()
        
        result = await fetch_page(mock_aiohttp_session, "https://example.com", mock_logger)
        
        assert result is None
        mock_logger.error.assert_called()


class TestExchangeRate:
    """Test exchange rate fetching."""
    
    @pytest.mark.asyncio 
    async def test_get_exchange_rate_success(self, mock_aiohttp_session, mock_logger):
        """Test successful exchange rate fetch."""
        # Mock response with exchange rate data
        mock_response = AsyncMock()
        mock_response.text.return_value = '{"rates": {"EUR": 0.85}}'
        mock_aiohttp_session.get.return_value.__aenter__.return_value = mock_response
        
        with patch('utils.fetch_page', return_value='{"rates": {"EUR": 0.85}}'):
            rate = await get_usd_to_eur_rate(mock_aiohttp_session, mock_logger)
        
        assert rate == 0.85
    
    @pytest.mark.asyncio
    async def test_get_exchange_rate_cached(self, mock_aiohttp_session, mock_logger):
        """Test cached exchange rate."""
        # Set up cache
        with patch('utils._exchange_rate_cache', {"rate": 0.85, "last_fetched": 999999999999}):
            rate = await get_usd_to_eur_rate(mock_aiohttp_session, mock_logger)
        
        assert rate == 0.85
        # Should not make HTTP request due to cache
        mock_aiohttp_session.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_exchange_rate_error(self, mock_aiohttp_session, mock_logger):
        """Test exchange rate fetch error."""
        clear_exchange_rate_cache()
        with patch('utils.fetch_page', return_value=None):
            rate = await get_usd_to_eur_rate(mock_aiohttp_session, mock_logger)
        
        assert rate is None
    
class TestPriceParsing:
    """Test price parsing functionality."""
    
    def test_parse_price_euro_formats(self):
        """Test parsing various Euro formats."""
        # Standard Euro format
        assert parse_price("€8,500.00") == Decimal("8500.00")
        assert parse_price("8.500,00 EUR") == Decimal("8500.00")
        assert parse_price("€ 1.234,56") == Decimal("1234.56")
        
        # Without decimal places
        assert parse_price("€8,500") == Decimal("8500")
        assert parse_price("8500 EUR") == Decimal("8500")
    
    def test_parse_price_usd_formats(self):
        """Test parsing USD formats."""
        assert parse_price("$10,250.50", "USD") == Decimal("10250.50") 
        assert parse_price("10,250.50 USD") == Decimal("10250.50")
        assert parse_price("$10,000") == Decimal("10000")
    
    def test_parse_price_edge_cases(self):
        """Test edge cases in price parsing."""
        # Price on request
        assert parse_price("Price on request") is None
        assert parse_price("Preis auf Anfrage") is None
        
        # Empty or None
        assert parse_price("") is None
        assert parse_price(None) is None
        
        # Invalid formats
        assert parse_price("Not a price") is None
        assert parse_price("€ABC") is None
    
    def test_parse_price_different_separators(self):
        """Test parsing with different thousand/decimal separators."""
        # European format (dot for thousands, comma for decimal)
        assert parse_price("1.234,56") == Decimal("1234.56")
        
        # US format (comma for thousands, dot for decimal)
        assert parse_price("1,234.56") == Decimal("1234.56")
        
        # Only thousands separator
        assert parse_price("1,234") == Decimal("1234")
        assert parse_price("1.234") == Decimal("1234")
    
    def test_parse_price_trailing_dot_dash(self):
        """A dash for "no cents" after a dot, as World of Time writes it."""
        assert parse_price("6,250.-") == Decimal("6250")
        assert parse_price("1,250,000.-") == Decimal("1250000")

    def test_parse_price_several_thousands_groups(self):
        assert parse_price("1.234.567") == Decimal("1234567")
        assert parse_price("1,234,567") == Decimal("1234567")

    def test_parse_price_trailing_comma_dash(self):
        """Test parsing prices with trailing comma-dash."""
        assert parse_price("8500,-") == Decimal("8500")
        assert parse_price("€1.234,- EUR") == Decimal("1234")


class TestYearParsing:
    """Test year extraction functionality."""
    
    def test_parse_year_with_keywords(self):
        """Test year parsing with keywords."""
        assert parse_year("Jahr 2020", "") == "2020"
        assert parse_year("Baujahr 1985", "") == "1985"
        assert parse_year("Year: 2019", "") == "2019"
        assert parse_year("original-papiere: ja (2018)", "") == "2018"
    
    def test_parse_year_with_circa(self):
        """Test year parsing with circa indicators.""" 
        assert parse_year("ca. 1995", "") == "1995"
        assert parse_year("um 2010", "") == "2010"
        assert parse_year("ca 1985", "") == "1985"
    
    def test_parse_year_standalone(self):
        """Test parsing standalone years."""
        assert parse_year("Beautiful watch from 2018", "") == "2018"
        assert parse_year("Vintage 1985 timepiece", "") == "1985"
    
    def test_parse_year_from_title(self):
        """Test year parsing from title parameter."""
        assert parse_year("Great condition", "Rolex Submariner 2020") == "2020"
        assert parse_year("", "Vintage Omega 1985") == "1985"
    
    def test_parse_year_invalid_ranges(self):
        """Test year parsing with invalid year ranges."""
        assert parse_year("Year 1850", "") is None  # Too old
        assert parse_year("Year 2050", "") is None  # Too new
        assert parse_year("Model 1234", "") is None  # Ambiguous

    def test_parse_year_skip_reference_context(self):
        """Test that reference numbers are skipped."""
        assert parse_year("Ref 2020 model", "") is None  # Reference context
        assert parse_year("SKU: 1985", "") is None  # SKU context
        assert parse_year("Article ID: 2000", "") is None  # Article context

    def test_parse_year_next_to_a_reference(self):
        """The year is found beside a number that only looks like one."""
        assert parse_year("Ref. 2020, Baujahr 2010", "") == "2010"
        assert parse_year("Blue Star, steel, very nice original condition, 1982", "") == "1982"
        assert parse_year("enamel dial, silver case, 1920", "") == "1920"

    def test_parse_year_after_a_reference(self):
        """A year that follows a reference, as vintage watches are titled, is the year."""
        assert parse_year("Omega Speedmaster Ref. 145.022, 1969", "") == "1969"
        assert parse_year("Ref. 116610LN, 2015", "") == "2015"
        assert parse_year("Ref. 2020 from 2020", "") == "2020"
        assert parse_year("Referenz 2015", "") is None

    @pytest.mark.parametrize(
        "text,year",
        [
            # Words that only end in, or contain, the letters of a label
            ("Rolex Day-Date President 1978", "1978"),
            ("Rolex Datejust 36 Jubilee President 1985", "1985"),
            ("Heuer Carrera Chrono. 1968", "1968"),
            ("Omega Seamaster Herrenmodell 1965", "1965"),
            ("modern 1995", "1995"),
            ("refurbished 2019", "2019"),
            # Labels, with and without "Nr"
            ("Art-Nr. 1985", None),
            ("Artikelnummer 2020", None),
            ("Ident-Nr. 1999", None),
            ("Ref. No. 1999", None),
            ("Modell 2015", None),
            ("Kal. 2000", None),
            ("No. 1950", None),
            ("P/N 2010", None),
        ],
    )
    def test_parse_year_beside_a_label(self, text, year):
        assert parse_year(text, "") == year
    
class TestBoxPapersParsing:
    """Test box and papers parsing."""
    
    def test_parse_both_box_and_papers(self):
        """Test parsing when both box and papers are mentioned."""
        papers, box = parse_box_papers("Box and papers included")
        assert papers is True
        assert box is True
        
        papers, box = parse_box_papers("Full set with box und papieren")
        assert papers is True
        assert box is True
    
    def test_parse_papers_only(self):
        """Test parsing papers status only."""
        papers, box = parse_box_papers("Papers: yes, original certificate")
        assert papers is True
        assert box is None

    @pytest.mark.xfail(
        strict=True,
        reason="'Papiere: nein' is read as papers present: every 'no papers' "
        "phrase contains a word from the 'has papers' list, which is checked first",
    )
    def test_parse_papers_absent(self):
        """A listing that says there are no papers must not show papers."""
        papers, box = parse_box_papers("Papiere: nein")
        assert papers is False
        assert box is None
    
    def test_parse_box_only(self):
        """Test parsing box status only.""" 
        papers, box = parse_box_papers("Original box included")
        assert papers is None
        assert box is True
        
        papers, box = parse_box_papers("Box: no")
        assert papers is None
        assert box is False

    def test_parse_no_accessories(self):
        """Test parsing when no accessories are included."""
        papers, box = parse_box_papers("Accessories: none")
        assert papers is False
        assert box is False
    
    def test_parse_empty_or_none(self):
        """Test parsing empty or None input."""
        papers, box = parse_box_papers("")
        assert papers is None
        assert box is None
        
        papers, box = parse_box_papers(None)
        assert papers is None
        assert box is None

    @pytest.mark.parametrize(
        "text, expected",
        [
            # The negation right before the word
            ("Ohne Papiere, mit Box", (False, True)),
            ("ohne Box und ohne Papiere", (False, False)),
            ("keine Papiere vorhanden", (False, None)),
            ("keine originalen Papiere", (False, None)),
            ("keinerlei Papiere", (False, None)),
            ("Kein Zertifikat", (False, None)),
            ("ohne Garantiekarte", (False, None)),
            ("Ohne Originalbox", (None, False)),
            ("without papers", (False, None)),
            ("no original box", (None, False)),
            # ... reaching a second word named with it
            ("Nur Uhr, keine Papiere oder Box vorhanden.", (False, False)),
            ("no box or papers", (False, False)),
            ("Uhr ohne Box/Papiere", (False, False)),
            ("Keine Box & Papiere", (False, False)),
            ("Weder Box noch Papiere", (False, False)),
            ("Weder Originalbox noch Garantiekarte", (False, False)),
            # A comma, another word, a field of its own or the line's end ends it
            ("Ohne Box, Papiere vorhanden", (True, False)),
            ("No box, papers included", (True, False)),
            ("Ohne Box Papiere vorhanden", (True, False)),
            ("Keine Papiere Box vorhanden", (False, True)),
            ("Ohne Box / Papiere: vorhanden", (True, False)),
            ("Ohne Box und Papiere: vorhanden", (True, False)),
            ("Sehr gut ohne Kratzer Box, Papiere", (True, True)),
            ("Ungetragen keine Kratzer Box und Papiere", (True, True)),
            ("No reserve box and papers", (True, True)),
            ("ohne\nBox", (None, True)),
            # A negation ending one line says nothing of the next
            ("Kratzer: keine\nBox: ja\nPapiere: ja", (True, True)),
            ("Polished: no\nBox: yes\nPapers: yes", (True, True)),
            ("Service: no\nPapers: yes", (True, None)),
            # A label before the negation changes nothing
            ("Zubehör: keine Papiere", (False, None)),
            ("Lieferumfang: keine Box und Papiere", (False, False)),
            ("Accessories: no box", (None, False)),
            ("Zubehör: keine Box und keine Papiere", (False, False)),
            ("Hinweis: keine Papiere", (False, None)),
            ("Lieferumfang: ohne Box und Papiere", (False, False)),
            ("Hinweis: ohne Box", (None, False)),
            ("Ohne Box: nur Uhr und Papiere", (True, False)),
            ("Zubehör: weder Box noch Papiere", (False, False)),
            # ... but not a word that heads a field saying it is there
            ("Gebrauchsspuren: ohne Box: ja", (None, True)),
            ("Kratzer: keine Box: ja", (None, True)),
            ("Kratzer: keine Box: ja Papiere: ja", (True, True)),
            ("Ohne Box und Papiere: vorhanden.", (True, False)),
            # ... whose whole value says so
            ("ohne Box: vorhanden sind nur Papiere", (True, False)),
            # A negation that is itself negated does not say they are missing
            ("Natürlich nicht ohne Papiere", (True, None)),
            ("Natürlich nicht ohne Box", (None, True)),
            ("Not without box and papers", (True, True)),
            # Papers are missing only when nothing else names them
            ("Box und Papiere, kein Zertifikat", (True, True)),
            ("Papiere dabei, kein Echtheitszertifikat", (True, None)),
            ("Box & Papiere, keine Garantiekarte", (True, True)),
            ("With papers, no certificate", (True, None)),
            ("Keine Garantiekarte, aber Papiere", (True, None)),
            ("Keine Servicepapiere, aber Garantiekarte von 2015", (True, None)),
            # A box said to be missing stays missing when it is merely named again
            ("Uhr ohne Box. Auf Wunsch liefern wir eine Uhrenbox gegen Aufpreis.", (None, False)),
            ("Ohne Box (die Box ist leider verloren gegangen), Papiere: ja", (True, False)),
            # ... unless the listing states that it is there
            ("Ohne Box. Box: ja", (None, True)),
            # A field's value is read as before
            ("Box: nein (Box beim Umzug verloren)", (None, False)),
            ("Box: none included", (None, False)),
            ("Box: no longer available", (None, False)),
            ("Original-Box: nein, Box kann nachgekauft werden", (None, False)),
            # A full set said to be missing leaves open which of the two is
            ("Kein Fullset", (None, None)),
            ("Kein Full Set, nur Box", (None, True)),
            ("No full set, box only", (None, True)),
            # A "no" about something else changes nothing
            ("kein Kratzer, Box und Papiere dabei", (True, True)),
            ("No scratches, box/papers", (True, True)),
            ("Submariner No Date mit Box und Papieren", (True, True)),
            # A dealer's offer on Kleinanzeigen
            (
                "Keine Papiere vorhanden, wir stellen ein eigenes Echtheitszertifikat aus"
                " ⊛ Keine Originalbox vorhanden",
                (False, False),
            ),
        ],
    )
    def test_parse_a_negation_right_before_the_word(self, text, expected):
        """(papers, box) where the listing says "ohne", "keine", "weder", "no" or "without" before them."""
        assert parse_box_papers(text) == expected

    @pytest.mark.parametrize(
        "text",
        [
            "ohne " + "Box und " * 20000 + "Papiere",
            "ohne " + "x" * 100000 + "box",
            "ohne " + "x" * 100000 + "papiere",
            "keine " + "x" * 100000 + "zertifikat",
            "x" * 200000,
            "keine " * 50000 + "Box",
            "original " * 50000 + "box",
            "uhr box papiere ohne kratzer " * 18000,
        ],
    )
    def test_a_long_text_of_such_words_is_read_at_once(self, text):
        """Half a megabyte takes a fraction of a second; a scan never waits on one description."""
        started = time.perf_counter()
        parse_box_papers(text)
        assert time.perf_counter() - started < 2


class TestConditionParsing:
    """Test condition parsing functionality."""
    
    def test_parse_condition_excellent(self):
        """Test parsing excellent conditions."""
        assert parse_condition("Ungetragen", "test") == "★★★★★"
        assert parse_condition("Mint condition", "test") == "★★★★★"
        assert parse_condition("New old stock", "test") == "★★★★★"
        assert parse_condition("Fabrikneu", "test") == "★★★★★"
    
    def test_parse_condition_very_good(self):
        """Test parsing very good conditions."""
        assert parse_condition("Excellent condition", "test") == "★★★★☆"
        assert parse_condition("Top Zustand", "test") == "★★★★☆"
        assert parse_condition("Very good condition", "test") == "★★★★☆"
    
    def test_parse_condition_good(self):
        """Test parsing good conditions."""
        assert parse_condition("Good condition", "test") == "★★★☆☆"
        assert parse_condition("Guter Zustand", "test") == "★★★☆☆"
        assert parse_condition("Leichte Gebrauchsspuren", "test") == "★★★☆☆"
    
    def test_parse_condition_fair(self):
        """Test parsing fair conditions."""
        assert parse_condition("Light wear", "test") == "★★☆☆☆"
        assert parse_condition("Fair condition", "test") == "★★☆☆☆"
    
    def test_parse_condition_poor(self):
        """Test parsing poor conditions."""
        assert parse_condition("Worn", "test") == "★☆☆☆☆"
        assert parse_condition("Signs of wear", "test") == "★☆☆☆☆"
        assert parse_condition("Deutliche Gebrauchsspuren", "test") == "★☆☆☆☆"
    
    def test_parse_condition_with_mappings(self):
        """Test condition parsing with custom mappings."""
        mappings = {
            "0": "★★★★★",
            "1": "★★★★☆", 
            "2": "★★★☆☆"
        }
        
        assert parse_condition("0", "test", mappings) == "★★★★★"
        assert parse_condition("1", "test", mappings) == "★★★★☆"
        assert parse_condition("unmapped", "test", mappings) is None
    
    def test_parse_condition_no_match(self):
        """Test condition parsing with no matches."""
        assert parse_condition("Random text", "test") is None
        assert parse_condition("", "test") is None
        assert parse_condition(None, "test") is None


class TestTextExtraction:
    """Test text extraction from HTML elements."""
    
    def test_extract_text_from_element(self):
        """Test text extraction from BeautifulSoup element."""
        html = "<div>Hello <span>World</span> Test</div>"
        soup = BeautifulSoup(html, 'html.parser')
        div = soup.find('div')
        
        text = extract_text_from_element(div)
        assert text == "Hello World Test"
    
    def test_extract_text_with_separator(self):
        """Test text extraction with custom separator."""
        html = "<div>Hello <span>World</span> Test</div>"
        soup = BeautifulSoup(html, 'html.parser')
        div = soup.find('div')
        
        text = extract_text_from_element(div, separator=" | ")
        assert text == "Hello | World | Test"
    
    def test_extract_text_from_none(self):
        """Test text extraction from None element."""
        text = extract_text_from_element(None)
        assert text == ""
    
    def test_extract_text_strips_whitespace(self):
        """Test that extracted text strips whitespace."""
        html = "<div>  Hello   <span>  World  </span>   Test  </div>"
        soup = BeautifulSoup(html, 'html.parser')
        div = soup.find('div')
        
        text = extract_text_from_element(div)
        assert text == "Hello World Test"


class TestTableDataParsing:
    """Test HTML table data parsing."""
    
    def test_parse_table_data_basic(self):
        """Test basic table data parsing."""
        html = """
        <table>
            <tr><th>Reference</th><td>116610LN</td></tr>
            <tr><th>Year:</th><td>2020</td></tr>
            <tr><th>Condition</th><td>Excellent</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, 'html.parser')
        table = soup.find('table')
        
        headers_map = {
            "reference": "reference",
            "year": "year", 
            "condition": "condition"
        }
        
        result = parse_table_data(table, headers_map)
        
        assert result["reference"] == "116610LN"
        assert result["year"] == "2020" 
        assert result["condition"] == "Excellent"
    
    def test_parse_table_data_mixed_cells(self):
        """Test table parsing with th and td cells."""
        html = """
        <table>
            <tr><td>Brand</td><td>Rolex</td></tr>
            <tr><th>Model:</th><td>Submariner</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, 'html.parser')
        table = soup.find('table')
        
        headers_map = {
            "brand": "brand",
            "model": "model"
        }
        
        result = parse_table_data(table, headers_map)
        
        assert result["brand"] == "Rolex"
        assert result["model"] == "Submariner"
    
    def test_parse_table_data_no_table(self):
        """Test table parsing with None table."""
        result = parse_table_data(None, {"test": "test"})
        assert result == {}
    
    def test_parse_table_data_no_matches(self):
        """Test table parsing with no header matches."""
        html = """
        <table>
            <tr><th>Other</th><td>Value</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, 'html.parser')
        table = soup.find('table')
        
        headers_map = {"known": "field"}
        result = parse_table_data(table, headers_map)
        
        assert result == {}

    def test_parse_table_data_insufficient_cells(self):
        """Test table parsing with rows having insufficient cells."""
        html = """
        <table>
            <tr><th>Reference</th><td>116610LN</td></tr>
            <tr><th>Incomplete</th></tr>
            <tr><th>Year</th><td>2020</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, 'html.parser')
        table = soup.find('table')
        
        headers_map = {
            "reference": "reference",
            "year": "year", 
            "incomplete": "incomplete"
        }
        
        result = parse_table_data(table, headers_map)
        
        assert result["reference"] == "116610LN"
        assert result["year"] == "2020"
        assert "incomplete" not in result  # Should skip incomplete rows