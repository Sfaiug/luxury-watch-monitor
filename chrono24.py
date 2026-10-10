"""What the watches the shops offer are offered for on Chrono24 inside the EU, kept in the price database.

Chrono24 turns a headless browser away, and from the server's own address any
browser at all, with Cloudflare's human check. A real Chrome on a screen of its
own, reaching the site through one of the owner's proxies, is let straight
through (measured on the server, 10 Oct 2026): so each search is a page in
Chrome through the next proxy.
"""

import asyncio
import contextlib
import itertools
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Dict, Iterator, List, Optional, Tuple
from urllib.parse import urlencode

from bs4 import BeautifulSoup

import proxies
from config import APP_CONFIG
from models import WatchData
from prices import Prices
from utils import parse_price

BASE_URL = "https://www.chrono24.de"
# Offers count only from inside the EU, VAT and all (owner rule, 10 Oct 2026):
# the countries as the owner's auction scanner names them to Chrono24
EU = (
    "DE", "BE", "FI", "PT", "BG", "DK", "LT", "LU", "HR", "LV",
    "FR", "HU", "SE", "MC", "SI", "SK", "IE", "EE", "MQ", "MT",
    "GP", "GR", "IT", "ES", "AT", "RE", "CY", "CZ", "PL", "RO", "NL",
)
PAGE = 120  # offers on a page, cheapest first: the cheapest quarter of up to 480
FRESH = timedelta(days=7)  # a reference is searched again once its offers are this old
ROUND = 20  # searches made with one Chrome before it is closed
PAUSE = 60  # seconds from one search to the next
IDLE = 600  # seconds to wait when no reference is due, or when Chrono24 refused


class NotResults(Exception):
    """Chrono24 answered with a page that holds no search result: its human check, or a page it has changed."""


def search(query: str, **narrowed) -> str:
    """Chrono24's search for a query, cheapest first."""
    asked = {**narrowed, "dosearch": "true", "query": query, "sortorder": 1}
    return f"{BASE_URL}/search/index.htm?{urlencode(asked, doseq=True)}"


def search_url(brand: Optional[str], reference: str) -> str:
    """The search for a watch's offers inside the EU, cheapest first."""
    return search(" ".join(filter(None, (brand, reference))), countryIds=EU, currencyId="EUR", pageSize=PAGE)


def read(html: str, brand: Optional[str], reference: str, seen: datetime) -> Tuple[int, List[WatchData]]:
    """How many offers a search found in all, and the ones on its page with a price."""
    soup = BeautifulSoup(html, "lxml")
    count = soup.find("strong", string=re.compile(r"^\s*[\d.]+ Inserate\s*$"))
    if count:
        found = int(re.sub(r"\D", "", count.get_text()))
    elif soup.find(string=re.compile("Keine Inserate gefunden")):
        found = 0
    else:
        title = soup.title.get_text(strip=True) if soup.title else ""
        raise NotResults(f"no search result on the page ({title or 'no title'})")

    offers = []
    for card in soup.select(".js-listing-item-container"):
        link = card.select_one("a.js-listing-item-link")
        shown = card.select_one(".wt-listing-item-price")
        price = parse_price(shown.get_text(strip=True)) if shown else None
        if not (link and price):
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
    return found, offers


async def _without_pictures(route):
    # The proxies' traffic is the owner's: pictures, fonts and films stay away
    if route.request.resource_type in ("image", "media", "font"):
        await route.abort()
    else:
        await route.continue_()


class Chrome:
    """One Chrome on a virtual screen of its own; each page in a fresh window through the next proxy."""

    def __init__(self, proxies: Iterator[Optional[Dict[str, str]]]):
        self._proxies = proxies

    async def __aenter__(self) -> "Chrome":
        from playwright.async_api import async_playwright

        self._open = contextlib.AsyncExitStack()
        try:
            screen = await asyncio.create_subprocess_exec(
                "Xvfb", "-displayfd", "1", "-screen", "0", "1400x900x24", "-nolisten", "tcp",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )
            self._open.push_async_callback(screen.wait)
            self._open.callback(screen.terminate)
            display = ":" + (await screen.stdout.readline()).decode().strip()
            playwright = await self._open.enter_async_context(async_playwright())
            self._browser = await playwright.chromium.launch(
                channel="chrome", headless=False, env={**os.environ, "DISPLAY": display}
            )
            self._open.push_async_callback(self._browser.close)
        except BaseException:
            await self._open.aclose()
            raise
        return self

    async def __aexit__(self, *exc):
        await self._open.aclose()

    async def page(self, url: str) -> str:
        window = await self._browser.new_context(locale="de-DE", proxy=next(self._proxies))
        try:
            await window.route("**/*", _without_pictures)
            page = await window.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            return await page.content()
        finally:
            await window.close()


async def search_round(prices: Prices, chrome, now=datetime.now) -> int:
    """Search Chrono24 for the references most due, one Chrome for the round; how many were searched.

    A page that is no search result ends the round with that reference still
    due: what refuses one search refuses the next.
    """
    due = prices.due(now() - FRESH, ROUND)
    if not due:
        return 0
    async with chrome as browser:
        for searched, (brand, reference) in enumerate(due):
            if searched:
                await asyncio.sleep(PAUSE)
            seen = now()
            found, offers = read(await browser.page(search_url(brand, reference)), brand, reference, seen)
            prices.searched(reference, found, offers, seen)
    return len(due)


async def keep_up(prices: Prices, logger: logging.Logger):
    """Keep Chrono24's offers for every reference the shops show at most a week old, until cancelled."""
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
                logger.info(f"Chrono24: searched {searched} references")
        await asyncio.sleep(PAUSE if searched else IDLE)
