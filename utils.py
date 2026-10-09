"""Utility functions for watch monitor application."""

import asyncio
import re
import time
from decimal import Decimal, InvalidOperation
from typing import Optional, Callable, TypeVar, List, Tuple, Dict, Any
from functools import wraps
import aiohttp
from bs4 import BeautifulSoup

from config import APP_CONFIG
from logging_config import PerformanceLogger

T = TypeVar("T")


# Exchange rate cache (module-level for cross-session sharing)
# Note: This is intentionally module-level to cache rates across all scrapers
# Memory footprint is minimal (2 values: float + timestamp)
_exchange_rate_cache = {"rate": None, "last_fetched": 0}


def clear_exchange_rate_cache():
    """Clear the exchange rate cache to release memory."""
    global _exchange_rate_cache
    _exchange_rate_cache = {"rate": None, "last_fetched": 0}


async def retry_with_backoff(
    func: Callable[..., T],
    max_retries: int = APP_CONFIG.max_retries,
    backoff_factor: float = APP_CONFIG.retry_backoff_factor,
    exceptions: tuple = (Exception,),
) -> T:
    """
    Retry a function with exponential backoff.

    Args:
        func: Async function to retry
        max_retries: Maximum number of retries
        backoff_factor: Multiplier for delay between retries
        exceptions: Tuple of exceptions to catch and retry

    Returns:
        Result of the function

    Raises:
        Last exception if all retries fail
    """
    delay = 1.0
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            return await func()
        except exceptions as e:
            last_exception = e
            if attempt < max_retries:
                await asyncio.sleep(delay)
                delay *= backoff_factor
            else:
                raise

    raise last_exception


async def fetch_page(
    session: aiohttp.ClientSession, url: str, logger=None
) -> Optional[str]:
    """
    Fetch a web page with error handling and retries.

    Args:
        session: aiohttp session
        url: URL to fetch
        logger: Optional logger instance

    Returns:
        Page content or None if failed
    """

    async def _fetch():
        headers = {"User-Agent": APP_CONFIG.user_agent}
        timeout = aiohttp.ClientTimeout(total=APP_CONFIG.request_timeout)

        async with session.get(url, headers=headers, timeout=timeout) as response:
            response.raise_for_status()
            text = await response.text()
            # Explicitly release response to free connection buffers
            await response.release()

            # ENHANCED: Monitor response size to identify problematic sites
            text_size_mb = len(text) / (1024 * 1024)
            if text_size_mb > 1.0:  # Warn if page exceeds 1MB
                if logger:
                    logger.warning(
                        f"Large response from {url}: {text_size_mb:.2f}MB "
                        f"({len(text):,} bytes) - may contribute to memory pressure"
                    )

            return text

    try:
        if logger:
            with PerformanceLogger(logger, f"fetching {url}"):
                return await retry_with_backoff(
                    _fetch, exceptions=(aiohttp.ClientError,)
                )
        else:
            return await retry_with_backoff(_fetch, exceptions=(aiohttp.ClientError,))
    except Exception as e:
        if logger:
            logger.error(f"Failed to fetch {url}: {e}")
        return None


async def get_usd_to_eur_rate(
    session: aiohttp.ClientSession, logger=None
) -> Optional[float]:
    """
    Get USD to EUR exchange rate with caching.

    Args:
        session: aiohttp session
        logger: Optional logger instance

    Returns:
        Exchange rate or None if failed
    """
    current_time = time.time()

    # Check cache
    if _exchange_rate_cache["rate"] and (
        current_time - _exchange_rate_cache["last_fetched"]
        < APP_CONFIG.exchange_rate_cache_duration
    ):
        return _exchange_rate_cache["rate"]

    # Fetch new rate
    try:
        if logger:
            logger.info("Fetching fresh USD to EUR exchange rate")

        content = await fetch_page(session, APP_CONFIG.exchange_rate_api_url, logger)
        if not content:
            return _exchange_rate_cache["rate"]

        import json

        data = json.loads(content)
        rate = data.get("rates", {}).get("EUR")

        if rate:
            _exchange_rate_cache["rate"] = float(rate)
            _exchange_rate_cache["last_fetched"] = current_time

            if logger:
                logger.info(f"Fetched new rate: 1 USD = {rate} EUR")

            return _exchange_rate_cache["rate"]

    except Exception as e:
        if logger:
            logger.error(f"Error fetching exchange rate: {e}")

    return _exchange_rate_cache["rate"]


def parse_price(price_text: str, currency: str = "EUR") -> Optional[Decimal]:
    """
    Parse price from various text formats.

    Args:
        price_text: Raw price text
        currency: Expected currency

    Returns:
        Decimal price or None if parsing fails
    """
    if not price_text:
        return None

    # Handle "price on request" cases
    if re.search(r"price.*on.*request|preis.*auf.*anfrage", price_text, re.IGNORECASE):
        return None

    # Clean the price string
    cleaned = price_text

    # Remove currency symbols and text
    cleaned = re.sub(r"[€$£¥₹CHF\s]|EUR|USD|GBP|CHF", "", cleaned, flags=re.IGNORECASE)

    # Remove trailing comma-dash
    cleaned = re.sub(r",-\s*$", "", cleaned)

    # Handle different decimal/thousand separators
    if "." in cleaned and "," in cleaned:
        # Determine which is decimal separator based on position
        if cleaned.rfind(".") < cleaned.rfind(","):
            # European format: 1.234,56
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            # US format: 1,234.56
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        # Check if comma is thousands separator or decimal
        parts = cleaned.split(",")
        if len(parts) == 2 and len(parts[-1]) == 3 and parts[0].isdigit():
            # Thousands separator: 1,234
            cleaned = cleaned.replace(",", "")
        else:
            # Decimal separator: 1234,56
            cleaned = cleaned.replace(",", ".")
    elif "." in cleaned:
        # Check if dot is thousands separator or decimal
        parts = cleaned.split(".")
        if len(parts) == 2 and len(parts[-1]) == 3 and parts[0].isdigit():
            # Thousands separator: 1.234
            cleaned = cleaned.replace(".", "")

    # Try to convert to Decimal
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


def parse_year(text: str, title: str = "") -> Optional[str]:
    """
    Extract year from text.

    Args:
        text: Text to search in
        title: Additional text to search (e.g., watch title)

    Returns:
        Year string or None
    """
    if not text and not title:
        return None

    search_texts = [text, title]

    for search_text in search_texts:
        if not search_text:
            continue

        # Look for year with keywords
        year_match = re.search(
            r"(?:jahr|year|baujahr|papers from|original-papiere: ja \()?"
            r"\s*(?:ca\.\s*|um\s*)?(\d{4})\b",
            search_text,
            re.IGNORECASE,
        )

        if year_match:
            year_val = year_match.group(1)
            year_int = int(year_val)
            if 1900 <= year_int <= 2030:
                return year_val

        # Look for standalone 4-digit years
        potential_years = re.findall(r"\b(19[5-9]\d|20[0-3]\d)\b", search_text)

        for year in potential_years:
            # Check context to avoid reference numbers
            idx = search_text.find(year)
            pre_context = search_text[max(0, idx - 15) : idx].lower()

            skip_prefixes = [
                "ref",
                "sku",
                "id:",
                "art-nr",
                "no.",
                "mod",
                "artikel",
                "p/n",
                "ident",
                "kal.",
            ]

            if not any(prefix in pre_context for prefix in skip_prefixes):
                year_int = int(year)
                if 1900 <= year_int <= 2030:
                    return year

    return None


# A word for papers or for a box, as a listing puts it right after "ohne",
# "keine" or "no": "Papiere", "originalen Papieren", "Garantiepapiere",
# "Zertifikat"; "Box", "Originalbox", "boxes"
_PAPERS_WORD = (
    r"(?:original\w*[\s-]+)?"
    r"\w*(?:papiere?n?|papers?|zertifikat\w*|certificates?|garantiekarten?)\b"
)
_BOX_WORD = r"(?:original\w*[\s-]+)?(?:\w*box(?:es|en)?\b|originalverpackung\w*)"
_EITHER_WORD = rf"(?:{_PAPERS_WORD}|{_BOX_WORD})"
# What a listing says is absent. The "no" stands right before the word and
# reaches a second one only across a connector standing on its own ("keine
# Papiere oder Box"); after a comma or a slash the listing says something new
_SAID_ABSENT = re.compile(
    rf"\b(?:ohne|keine?n?|no|without)\s+{_EITHER_WORD}"
    rf"(?:\s+(?:&|or|oder|und|and|noch)\s+{_EITHER_WORD})*"
    # "Papiere: nein", "Box: no"; not "Papers: No. 12345"
    rf"|{_EITHER_WORD}\s*:\s*(?:nein|none|no(?!\.?\s*\d))\b"
)
# What says they are there, wherever it stands in a word ("Garantiepapieren")
_BOTH_PRESENT = (
    "box and paper",
    "box und papieren",
    "fullset",
    "full set",
    "box & papers",
    "box, papiere",
)
_PAPERS_PRESENT = (
    "papiere",
    "papers",
    "certificate",
    "garantiekarte",
    "service karte",
    "originalzertifikat",
    "zertifikat vorhanden",
    "mit zertifikat",
)
_BOX_PRESENT = re.compile(r"box(?!er)|originalverpackung")


def parse_box_papers(text: str) -> Tuple[Optional[bool], Optional[bool]]:
    """
    Parse box and papers status from text.

    Args:
        text: Text to parse

    Returns:
        Tuple of (has_papers, has_box) booleans; None where the text does not say
    """
    if not text:
        return None, None

    text_lower = text.lower()
    if "accessories: none" in text_lower or "accessories:none" in text_lower:
        return False, False

    # Cut out what the listing says is absent; the rest is read as before
    said_absent = " ".join(match.group(0) for match in _SAID_ABSENT.finditer(text_lower))
    rest = _SAID_ABSENT.sub(" | ", text_lower)

    if any(phrase in rest for phrase in _BOTH_PRESENT):
        return True, True

    has_papers = has_box = None
    if any(word in rest for word in _PAPERS_PRESENT):
        has_papers = True
    elif re.search(_PAPERS_WORD, said_absent):
        has_papers = False
    if _BOX_PRESENT.search(rest):
        has_box = True
    elif re.search(_BOX_WORD, said_absent):
        has_box = False

    return has_papers, has_box


def parse_condition(
    text: str, site_key: str = "", mappings: Dict[str, str] = None
) -> Optional[str]:
    """
    Parse condition from text.

    Args:
        text: Text to parse
        site_key: Site identifier for site-specific logic
        mappings: Optional condition mappings

    Returns:
        Condition display string
    """
    if not text:
        return None

    text_lower = text.lower()

    # Site-specific mappings
    if mappings:
        text_stripped = text.strip()
        if text_stripped in mappings:
            return mappings[text_stripped]
        if text_lower.strip() in mappings:
            return mappings[text_lower.strip()]

    # Common condition keywords
    conditions = [
        (
            [
                "ungetragen",
                "unworn",
                "new old stock",
                "nos",
                "fabrikneu",
                "mint",
                " neu ",
                " new ",
                "neuwertig",
            ],
            "★★★★★",
        ),
        (
            [
                "excellent",
                "very nice original condition",
                "top zustand",
                "makellos",
                "near mint",
                "perfekter zustand",
                "sehr guter zustand",
                "very good condition",
                "1a zustand",
            ],
            "★★★★☆",
        ),
        (
            [
                "leichte gebrauchsspuren",
                "leichte tragespuren",
                "good condition",
                "nice condition",
                "gut erhalten",
                "guter zustand",
                "gebraucht",
            ],
            "★★★☆☆",
        ),
        (
            ["light wear", "fair condition", "sichtbare gebrauchsspuren", "getragen"],
            "★★☆☆☆",
        ),
        (
            [
                "gebrauchsspuren",
                "worn",
                "signs of wear",
                "deutliche gebrauchsspuren",
                "strong signs of use",
                "starke gebrauchsspuren",
            ],
            "★☆☆☆☆",
        ),
    ]

    for keywords, rating in conditions:
        if any(kw in text_lower for kw in keywords):
            return rating

    return None


def extract_text_from_element(element, separator: str = " ") -> str:
    """
    Extract and clean text from BeautifulSoup element.

    Args:
        element: BeautifulSoup element
        separator: String to join text parts

    Returns:
        Cleaned text
    """
    if not element:
        return ""

    # Get all text, preserving some structure
    texts = []
    for string in element.stripped_strings:
        texts.append(string)

    return separator.join(texts)


def parse_table_data(table_soup, headers_map: Dict[str, str]) -> Dict[str, str]:
    """
    Parse data from HTML table with header mappings.

    Args:
        table_soup: BeautifulSoup table element
        headers_map: Mapping of header text to field names

    Returns:
        Dictionary of parsed data
    """
    result = {}

    if not table_soup:
        return result

    for row in table_soup.find_all("tr"):
        cells = row.find_all(["th", "td"])

        if len(cells) >= 2:
            header = (
                extract_text_from_element(cells[0]).lower().replace(":", "").strip()
            )
            value = extract_text_from_element(cells[1])

            # Match against headers map
            for header_key, field_name in headers_map.items():
                if header_key.lower() in header:
                    result[field_name] = value
                    break

    return result
