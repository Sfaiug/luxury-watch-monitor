"""Bachmann & Scher scraper implementation."""

from typing import Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scrapers.base import BaseScraper
from models import WatchData
from utils import parse_price, parse_condition, parse_box_papers, extract_text_from_element


class BachmannScherScraper(BaseScraper):
    """Scraper for bachmann-scher.de."""

    async def _extract_watches(self, soup: BeautifulSoup) -> List[WatchData]:
        """Extract watches from the Bachmann & Scher listing page."""
        watches = []

        for card in soup.select("div.watch-item"):
            try:
                watch = self._parse_watch_element(card)
                if watch:
                    watches.append(watch)
            except Exception as e:
                self.logger.error(f"Error parsing watch element: {e}")

        return watches

    def _parse_watch_element(self, card) -> Optional[WatchData]:
        """Parse one card of the listing page."""
        # A watch still reserved for B&S PLUS members has no page of its own
        # yet; a sold one carries the sold flag
        link = card.select_one("div.watch-image a[href]")
        if not link or card.select_one("img.watch-sold-flag"):
            return None

        brand = extract_text_from_element(card.select_one("div.watch-name h3"))
        image = link.select_one("img[src]")

        return WatchData(
            title=extract_text_from_element(card.select_one("span.split-title"))
            or brand,
            url=urljoin(self.config.base_url, link["href"]),
            site_name=self.config.name,
            site_key=self.config.key,
            brand=brand or None,
            price=parse_price(
                extract_text_from_element(card.select_one("div.watch-preis")), "EUR"
            ),
            currency="EUR",
            image_url=urljoin(self.config.base_url, image["src"]) if image else None,
        )

    async def _extract_watch_details(self, watch: WatchData, soup: BeautifulSoup):
        """Extract model, specifications and pictures from the watch's own page."""
        model = extract_text_from_element(
            soup.select_one("div.watches-detailview hgroup h3")
        )
        if model:
            watch.model = model

        labelled, unlabelled = self._parse_spec_rows(soup)

        if labelled.get("referenz"):
            watch.reference = labelled["referenz"]
        if labelled.get("produktionsjahr"):
            watch.year = labelled["produktionsjahr"]
        if labelled.get("gehäuse material"):
            watch.case_material = labelled["gehäuse material"]
        if labelled.get("durchmesser"):
            watch.diameter = f"{labelled['durchmesser']} mm"
        if labelled.get("zustand"):
            watch.condition = parse_condition(
                labelled["zustand"], self.config.key, self.config.condition_mappings
            )

        # "Mit Box" and "Mit Papieren" rows say they come with the watch. Without
        # the row, the listing's title may still name them; if it does not, the
        # shop has said nothing either way
        papers_in_title, box_in_title = parse_box_papers(watch.title)
        watch.has_box = True if "Mit Box" in unlabelled else box_in_title
        watch.has_papers = True if "Mit Papieren" in unlabelled else papers_in_title

        image_urls = [
            urljoin(self.config.base_url, link["href"])
            for link in soup.select("div.watches-detailview a.lightbox[href]")
        ]
        if image_urls:
            watch.image_urls = image_urls

    def _parse_spec_rows(self, soup: BeautifulSoup) -> tuple[Dict[str, str], List[str]]:
        """Read the specification tables: labelled rows by label, and the rest."""
        labelled, unlabelled = {}, []

        for row in soup.select("div.watches-detailview table.table-watch tr"):
            value = extract_text_from_element(row.select_one("td.td-content"))
            if not value:
                continue
            label = extract_text_from_element(row.select_one("td.td-label")).lower()
            if label:
                labelled[label] = value
            else:
                unlabelled.append(value)

        return labelled, unlabelled
