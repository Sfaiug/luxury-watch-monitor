"""Kleinanzeigen: a search of the watch category, read like a shop's listing page."""

import json
import re
from typing import List, Optional
from urllib.parse import quote

from bs4 import BeautifulSoup

from scrapers.base import BaseScraper
from models import WatchData
from utils import parse_price, extract_text_from_element

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
        """Parse one offer from what its card states as data: title, price, picture and address.

        Nothing is read out of the seller's own words. The card holds only the
        start of them, cut off mid-word, and a reference, year, condition,
        papers or box taken from free text is wrong too often.
        """
        # An offer posted without a picture has no JSON-LD block, which names the picture
        ad = card.select_one('script[type="application/ld+json"]')
        # The price has an element of its own. A reduced offer's old price follows
        # it, struck through; the seller's text may name other amounts
        price_text = extract_text_from_element(card.select_one("p.text-title3"))

        watch = WatchData(
            title=extract_text_from_element(card.select_one("h3")),
            # By its number alone: the site's own link holds the title, and a
            # seller who edits the title would make it a new offer
            url=f"{BASE_URL}/s-anzeige/{card['data-adid']}",
            site_name=self.config.name,
            site_key=self.config.key,
            price=parse_price(price_text.replace("VB", ""), "EUR"),
            currency="EUR",
            image_url=json.loads(ad.string).get("contentUrl") if ad else None,
        )
        # "VB": the seller takes offers
        if watch.price and "VB" in price_text:
            watch.price_display += " VB"
        return watch
