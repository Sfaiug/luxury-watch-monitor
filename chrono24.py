"""What a watch is offered for on Chrono24 inside the EU: the search for it, and what its page says."""

import re
from datetime import datetime
from typing import List, Optional, Tuple
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from models import WatchData
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


class NotResults(Exception):
    """Chrono24 answered with a page that holds no search result: its human check, or a page it has changed."""


def search_url(brand: Optional[str], reference: str) -> str:
    """The search for a watch's offers inside the EU, cheapest first."""
    query = quote_plus(" ".join(filter(None, (brand, reference))))
    countries = "&".join(f"countryIds={country}" for country in EU)
    return (
        f"{BASE_URL}/search/index.htm?{countries}&currencyId=EUR&dosearch=true"
        f"&pageSize={PAGE}&query={query}&sortorder=1"
    )


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
