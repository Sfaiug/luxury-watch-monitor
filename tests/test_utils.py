"""Tests for utility functions."""

import pytest
import asyncio
import json
import aiohttp
from decimal import Decimal, InvalidOperation
from unittest.mock import AsyncMock, Mock, patch
from bs4 import BeautifulSoup

from utils import (
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
        
        papers, box = parse_box_papers("Papiere: nein")
        assert papers is False
        assert box is None
    
    def test_parse_box_only(self):
        """Test parsing box status only.""" 
        papers, box = parse_box_papers("Original box included")
        assert papers is None
        assert box is True
        
        papers, box = parse_box_papers("Box: no")
        assert papers is False  # Should be None for box
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
            <tr><th>Unknown</th><td>Value</td></tr>
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