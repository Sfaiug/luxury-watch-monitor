"""What the watches the shops offer are offered for on Chrono24 inside the EU, kept in the price database.

Chrono24 turns a headless browser away, and from the server's own address any
browser at all, with Cloudflare's human check. A real Chrome on a screen of its
own, reaching the site through one of the owner's proxies, is let straight
through (measured on the server, 10 Oct 2026): so each search is a page in
Chrome through the next proxy.
"""

import asyncio
import itertools
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, Iterator, List, Optional, Tuple
from urllib.parse import urlencode

from bs4 import BeautifulSoup
from playwright.async_api import Error as PageError

import chrome
import proxies
from config import APP_CONFIG
from models import WatchData
from prices import Prices
from utils import parse_price

BASE_URL = "https://www.chrono24.de"
# Offers count only from inside the EU, VAT and all (owner rule, 10 Oct 2026):
# the EU's VAT area, its 27 states and Monaco, which France's VAT covers
EU = (
    "DE", "BE", "FI", "PT", "BG", "DK", "LT", "LU", "HR", "LV",
    "FR", "HU", "SE", "MC", "SI", "SK", "IE", "EE", "MT",
    "GR", "IT", "ES", "AT", "CY", "CZ", "PL", "RO", "NL",
)
PAGE = 120  # offers on a page, cheapest first: the cheapest quarter of up to 480
# Searched around the clock, the oldest first (owner rule, 11 Oct 2026: prices "change all the time"):
# a search is made again once all others are, and an hour after it at the earliest
FRESH = timedelta(hours=1)
ROUND = 20  # searches made with one Chrome before it is closed
PAUSE = 60  # seconds from one search to the next
IDLE = 600  # seconds to wait when no reference is due, or when Chrono24 refused


USED, FULL_SET = "used", "full set"
# The watches a seller's is held against, as Chrono24's own filters ask for them: used ones, and
# used ones with the original box and papers. New and unworn ones would raise the price of a used one
KINDS = {
    USED: {"usedOrNew": "used"},
    # Original box and papers, both: 103 (box) and 104 (papers) asked together find either
    FULL_SET: {"usedOrNew": "used", "specials": "102"},
}


class NotResults(Exception):
    """Chrono24 answered with a page whose search results cannot be read."""


def search(query: str, **narrowed) -> str:
    """Chrono24's search for a query, cheapest first."""
    asked = {**narrowed, "dosearch": "true", "query": query, "sortorder": 1}
    return f"{BASE_URL}/search/index.htm?{urlencode(asked, doseq=True)}"


def search_url(brand: Optional[str], reference: str, kind: str) -> str:
    """The search for the offers of this kind of a watch inside the EU, cheapest first."""
    return search(
        " ".join(filter(None, (brand, reference))), countryIds=EU, currencyId="EUR", pageSize=PAGE, **KINDS[kind]
    )


def read(html: str, brand: Optional[str], reference: str, seen: datetime, page: int = 1) -> Tuple[int, List[WatchData]]:
    """The total search count for pagination, including unpriced offers, and this page's priced offers."""
    soup = BeautifulSoup(html, "lxml")
    count = soup.find("strong", string=re.compile(r"^\s*[\d.]+ Inserate\s*$"))
    if count:
        found = int(re.sub(r"\D", "", count.get_text()))
    elif soup.find(string=re.compile("Keine Inserate gefunden")):
        found = 0
    else:
        title = soup.title.get_text(strip=True) if soup.title else ""
        raise NotResults(f"no search result on the page ({title or 'no title'})")

    offers, cards = [], 0
    for card in soup.select(".js-listing-item-container"):
        link = card.select_one("a.js-listing-item-link")
        shown = card.select_one(".wt-listing-item-price")
        if not (link and shown):
            continue
        cards += 1  # read, with a price or "Preis auf Anfrage"
        price = parse_price(shown.get_text(strip=True))
        if not price:
            continue
        lines = [p.get_text(" ", strip=True) for p in link.select("div > p.text-ellipsis")]
        offers.append(
            WatchData(
                title=" ".join(lines),
                url=BASE_URL + link["href"],
                site_name="Chrono24",
                site_key="chrono24",
                brand=brand,
                model=lines[0] if lines else None,
                reference=reference,
                price=price,
                scraped_at=seen,
            )
        )
    expected = min(max(found - (page - 1) * PAGE, 0), PAGE)
    # Losing most of a page's cards means its markup changed
    if cards < expected / 2:
        raise NotResults(f"could not read search result: {cards} of {expected} expected offers ({found} found)")
    return found, offers


async def _without_pictures(route):
    # The proxies' traffic is the owner's: pictures, fonts and films stay away
    if route.request.resource_type in ("image", "media", "font"):
        await route.abort()
    else:
        await route.continue_()


class Chrome(chrome.Chrome):
    """Chrome, each page in a fresh window through the next proxy."""

    def __init__(self, proxies: Iterator[Optional[Dict[str, str]]]):
        self._proxies = proxies

    async def page(self, url: str) -> str:
        window = await self.window(proxy=next(self._proxies))
        try:
            await window.route("**/*", _without_pictures)
            page = await window.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            return await page.content()
        finally:
            await window.close()


async def search_round(prices: Prices, chrome, now=datetime.now) -> int:
    """Make the Chrono24 searches most due, one Chrome for the round; how many were made.

    A page that fails to load leaves its search due and goes on to the next.
    A page that is no search result ends the round with that search still
    due: what refuses one search refuses the next.
    """
    due = prices.due(list(KINDS), now() - FRESH, ROUND)
    if not due:
        return 0
    searched = 0
    async with chrome as browser:
        for attempted, (brand, reference, kind) in enumerate(due):
            if attempted:
                await asyncio.sleep(PAUSE)
            seen = now()
            url = search_url(brand, reference, kind)
            try:
                found, offers = read(await browser.page(url), brand, reference, seen)
                # Count priced offers throughout the search, keeping only the cheapest page of them.
                for page in range(2, (found + PAGE - 1) // PAGE + 1):
                    await asyncio.sleep(PAUSE)
                    _, more = read(await browser.page(f"{url}&showPage={page}"), brand, reference, seen, page=page)
                    offers.extend(more)
            except PageError as e:
                logging.getLogger(__name__).warning(f"Chrono24: page failed to load for {reference} ({kind}): {e}")
                continue
            prices.searched(reference, kind, len(offers), offers[:PAGE], seen)
            searched += 1
    return searched


async def keep_up(prices: Prices, logger: logging.Logger):
    """Keep searching Chrono24 for every reference, the oldest search first, until cancelled."""
    # One proxy after the other, round after round; straight without any
    ways = itertools.cycle(proxies.for_browser(APP_CONFIG.proxies_file) or [None])
    while True:
        try:
            searched = await search_round(prices, Chrome(ways))
        except Exception as e:
            logger.warning(f"Chrono24: searching stopped: {e}")
            searched = 0
        else:
            if searched:
                logger.info(f"Chrono24: made {searched} searches")
        await asyncio.sleep(PAUSE if searched else IDLE)
