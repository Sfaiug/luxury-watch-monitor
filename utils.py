"""Utility functions for watch monitor application."""

import asyncio
import re
import time
from decimal import Decimal, InvalidOperation
from typing import Optional, Callable, TypeVar, List, Tuple, Dict, Any
from functools import wraps
from urllib.parse import urlsplit
import aiohttp
from bs4 import BeautifulSoup

import proxies
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

    A site that refuses the request (403, 429) is asked again, and from then
    on, through the proxies in proxies.txt, when there are any.

    Args:
        session: aiohttp session
        url: URL to fetch
        logger: Optional logger instance

    Returns:
        Page content or None if failed
    """

    host = urlsplit(url).netloc

    async def _fetch():
        headers = {"User-Agent": APP_CONFIG.user_agent}
        timeout = aiohttp.ClientTimeout(total=APP_CONFIG.request_timeout)

        async with session.get(
            url, headers=headers, timeout=timeout, **proxies.ROUTES.way_to(host)
        ) as response:
            if response.status in (403, 429) and proxies.ROUTES.refused(host) and logger:
                logger.warning(
                    f"{host} refused the request ({response.status}); "
                    "its requests go through a proxy from now on"
                )
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

    # Remove a trailing "no cents" dash: 8.500,- or 6,250.-
    cleaned = re.sub(r"[.,]-+$", "", cleaned)

    # Handle different decimal/thousand separators
    if "." in cleaned and "," in cleaned:
        # Determine which is decimal separator based on position
        if cleaned.rfind(".") < cleaned.rfind(","):
            # European format: 1.234,56
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            # US format: 1,234.56
            cleaned = cleaned.replace(",", "")
    else:
        separator = "," if "," in cleaned else "."
        parts = cleaned.split(separator)
        if (
            len(parts) > 1
            and parts[0].isdigit()
            and all(len(part) == 3 for part in parts[1:])
        ):
            # Thousands separator: 1,234 or 1.234.567
            cleaned = "".join(parts)
        else:
            # Decimal separator: 1234,56
            cleaned = cleaned.replace(",", ".")

    # Try to convert to Decimal
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


# The end of a text whose next number is a reference, article or movement
# number: the label as a word of its own ("Ref", "Referenz", "SKU", "ID",
# "Art-Nr", "Artikel", "Mod", "Modell", "P/N", "Ident", "Kal", "No", "Nr"),
# then at most "Nr"/"No"/"Nummer" and punctuation. "President", "Chrono."
# and "Herrenmodell" end in such letters without being one
_NUMBER_LABEL = re.compile(
    r"\b(?:ref(?:erenz\w*|erence\w*)?|sku|id|art-nr|artikel\w*|mod(?:ell\w*)?"
    r"|p/n|ident\w*|kal|no|nr)"
    r"(?:[-\s.]*(?:nr|no|nummer|number)\b)?[\s.:#-]*$"
)


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
            r"(?:jahr|year|baujahr|papers from|original-papiere: ja \()"
            r"\s*(?:ca\.\s*|um\s*)?(\d{4})\b",
            search_text,
            re.IGNORECASE,
        )

        if year_match:
            year_val = year_match.group(1)
            year_int = int(year_val)
            if 1900 <= year_int <= 2030:
                return year_val

        # A year standing on its own. A number that directly follows a label
        # for a reference or article number ("Ref. 2020", "Art-Nr. 1985") is none
        for match in re.finditer(r"\b(19\d\d|20[0-3]\d)\b", search_text):
            if _NUMBER_LABEL.search(search_text[: match.start()].lower()):
                continue
            if 1900 <= int(match.group(1)) <= 2030:
                return match.group(1)

    return None


# A word for papers, for a box, or for both at once, as a listing names them
# when it says they are missing: "Papiere", "originalen Papieren",
# "Garantiepapiere", "Zertifikat"; "Box", "Originalbox", "boxes"; "Full Set"
_PAPERS_WORD = (
    r"(?:original\w*[ -]+)?"
    r"\w*(?:papiere?n?|papers?|zertifikat\w*|certificates?|garantiekarten?)\b"
)
_BOX_WORD = r"(?:original\w*[ -]+)?(?:\w*box(?:es|en)?\b|originalverpackung\w*)"
_NAMED = rf"\b(?:{_PAPERS_WORD}|{_BOX_WORD}|full ?set\b)"
# What a listing says is missing by the negation right before it, on the same
# line: "ohne Papiere", "keine Box/Papiere", "weder Box noch Papiere", "no box
# or papers", "kein Fullset". A comma does not join: after it the listing says
# something new. Nor does the negation reach a word that heads a field of its
# own: "ohne Box / Papiere: vorhanden". A negation that is a field's own value
# ("Kratzer: keine Box: ja") or is itself negated ("nicht ohne Papiere") does
# not say they are missing
_SAID_ABSENT = re.compile(
    r"(?P<not_of_them>(?::|\b(?:nicht|not)\b)[^\S\n]*)?"
    r"\b(?:ohne|kein\w*|weder|no|without)[^\S\n]+"
    rf"{_NAMED}"
    r"(?:(?:[^\S\n]+(?:or|oder|und|and|noch)[^\S\n]+|[^\S\n]*[/&][^\S\n]*)"
    rf"{_NAMED}(?![^\S\n]*:)){{0,3}}"
)


def parse_box_papers(text: str) -> Tuple[Optional[bool], Optional[bool]]:
    """
    Parse box and papers status from text.

    Args:
        text: Text to parse

    Returns:
        Tuple of (has_papers, has_box) booleans
    """
    if not text:
        return None, None

    text_lower = text.lower()

    # Cut out what the listing says is missing. What the rest states to be
    # there counts first, then what was said to be missing, and a mere mention
    # last: "Ohne Papiere, die Papiere hat der Vorbesitzer" has no papers. A
    # full set said to be missing leaves open which of the two is
    missing = []

    def cut(said):
        if said.group("not_of_them"):
            return said.group(0)
        missing.append(said.group(0))
        return " | "

    rest = _SAID_ABSENT.sub(cut, text_lower)
    said_absent = " ".join(missing)

    # Check for both together
    both_keywords = [
        "box and paper",
        "box und papieren",
        "fullset",
        "full set",
        "box & papers",
        "box, papiere",
    ]

    if any(kw in rest for kw in both_keywords):
        return True, True

    # Check papers
    has_papers = None
    papers_yes = [
        "papers: yes",
        "papiere: ja",
        "original-papiere: ja",
        "originalzertifikat",
        "zertifikat vorhanden",
        "mit papieren",
        "original papieren",
        "mit zertifikat",
        "papiere vorhanden",
        "service karte",
        "garantiekarte",
        "certificate",
    ]

    if any(kw in rest for kw in papers_yes):
        has_papers = True
    elif re.search(_PAPERS_WORD, said_absent):
        has_papers = False
    elif "papiere" in rest or "papers" in rest:
        has_papers = True  # Default to yes if papers are mentioned

    # Check box
    has_box = None
    box_yes = [
        "box: yes",
        "box: ja",
        "original-box: ja",
        "original box",
        "originalbox",
        "mit box",
        "originalverpackung",
        "box vorhanden",
    ]

    box_no = ["box: no", "box: nein", "ohne box", "original-box: nein"]

    if any(kw in rest for kw in box_yes):
        has_box = True
    elif re.search(_BOX_WORD, said_absent) or any(kw in text_lower for kw in box_no):
        has_box = False
    elif "box" in rest:
        has_box = True  # Default to yes if "box" is mentioned

    # Check for "no accessories"
    if "accessories: none" in text_lower or "accessories:none" in text_lower:
        has_papers = False
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
