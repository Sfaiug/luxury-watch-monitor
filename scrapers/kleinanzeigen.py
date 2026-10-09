"""Kleinanzeigen: a search of the watch category, read like a shop's listing page."""

import json
import re
from typing import List, Optional
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from scrapers.base import BaseScraper
from models import WatchData
from utils import parse_price, parse_year, parse_condition, extract_text_from_element

BASE_URL = "https://www.kleinanzeigen.de"
SELLERS = {"private": "anbieter:privat/", "dealer": "anbieter:gewerblich/", "any": ""}


def search_url(
    words: str,
    min_price: Optional[int] = None,
    max_price: Optional[int] = None,
    seller: str = "any",
) -> str:
    """The newest watch offers for these words, filtered by the site itself."""
    price = ""
    if min_price or max_price:
        price = f"preis:{min_price or ''}:{max_price or ''}/"
    # A slash would start a new part of the address: it separates words like a space
    slug = "-".join(quote(word) for word in re.split(r"[\s/]+", words.lower()) if word)
    return f"{BASE_URL}/s-uhren-schmuck/anzeige:angebote/{SELLERS[seller]}{price}{slug}/k0c157"


class KleinanzeigenScraper(BaseScraper):
    """Reads the result page of a Kleinanzeigen search (config.url)."""

    async def _extract_watches(self, soup: BeautifulSoup) -> List[WatchData]:
        """Extract the offers from a search result page."""
        watches = []

        for card in soup.select("article[data-adid]"):
            try:
                watches.append(self._parse_watch_element(card))
            except Exception as e:
                self.logger.error(f"Error parsing watch element: {e}")

        return watches

    def _parse_watch_element(self, card) -> WatchData:
        """Parse one offer; its title, full description and picture come as JSON-LD."""
        ad = json.loads(card.select_one('script[type="application/ld+json"]').string)
        title = ad["title"]
        text = f"{title}\n{ad.get('description') or ''}"

        # The price has an element of its own. A reduced offer's old price follows
        # it, struck through; the seller's text may name other amounts
        price_text = extract_text_from_element(card.select_one("p.text-title3"))
        reference = re.search(r"\bRef(?:erenz)?\b[.:\s]*([A-Z0-9][\w./-]{2,})", text)

        watch = WatchData(
            title=title,
            url=urljoin(BASE_URL, card["data-href"]),
            site_name=self.config.name,
            site_key=self.config.key,
            reference=reference.group(1) if reference else None,
            year=parse_year(text),
            price=parse_price(price_text.replace("VB", ""), "EUR"),
            currency="EUR",
            condition=parse_condition(text, self.config.key),
            image_url=ad.get("contentUrl"),
        )
        # "VB": the seller takes offers
        if watch.price and "VB" in price_text:
            watch.price_display += " VB"
        return watch
