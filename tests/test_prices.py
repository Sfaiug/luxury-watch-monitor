"""What the monitor remembers of the offers it reads."""

import logging
import sqlite3
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from config import SITE_CONFIGS
from models import ScrapingSession, WatchData
from monitor import WatchMonitor
from prices import Prices, reference_key
from scrapers.kleinanzeigen import KleinanzeigenScraper


def offer(path="/uhren/rolex-submariner-116610ln", price="11550", day=1, shop="worldoftime", **stated):
    stated.setdefault("reference", "116610LN")
    return WatchData(
        title="Rolex Submariner Date",
        url=f"https://shop.example{path}?ref=newest",
        site_name=SITE_CONFIGS[shop].name,
        site_key=shop,
        price=Decimal(price) if price else None,
        scraped_at=datetime(2026, 10, day, 12, 0),
        **stated,
    )


@pytest.fixture
def prices(tmp_path):
    return Prices(tmp_path / "prices.sqlite3")


def kept(prices):
    prices._db.row_factory = sqlite3.Row
    return [dict(row) for row in prices._db.execute("SELECT * FROM offers ORDER BY first_seen, address")]


def test_an_offer_is_remembered_with_what_it_states(prices):
    prices.saw([offer(brand="Rolex", model="Submariner Date", year="2018", has_box=True, has_papers=False)])

    assert kept(prices) == [
        {
            "site_key": "worldoftime",
            "address": "/uhren/rolex-submariner-116610ln",
            "reference": "116610LN",
            "price": 11550.0,
            "brand": "Rolex",
            "model": "Submariner Date",
            "year": "2018",
            "condition": None,
            "has_box": 1,
            "has_papers": 0,
            "first_seen": "2026-10-01T12:00:00",
            "last_seen": "2026-10-01T12:00:00",
        }
    ]


def test_an_offer_seen_again_keeps_its_first_day_and_takes_the_new_price(prices):
    prices.saw([offer(day=1)])
    # As the listing page shows a known offer: no reference, which only its own page names
    prices.saw([offer(day=9, price="10990", reference=None)])

    (row,) = kept(prices)
    assert (row["first_seen"], row["last_seen"]) == ("2026-10-01T12:00:00", "2026-10-09T12:00:00")
    assert (row["reference"], row["price"]) == ("116610LN", 10990.0)


def test_an_offer_seen_again_without_a_price_keeps_the_one_it_had(prices):
    prices.saw([offer(day=1)])
    prices.saw([offer(day=2, price=None)])

    (row,) = kept(prices)
    assert (row["price"], row["last_seen"]) == (11550.0, "2026-10-02T12:00:00")


def test_only_an_offer_with_a_reference_and_a_price_in_euros_is_kept(prices):
    prices.saw(
        [
            offer("/a", reference=None),
            offer("/b", price=None),
            offer("/c", currency="USD"),
            offer("/d"),
        ]
    )

    assert [row["address"] for row in kept(prices)] == ["/d"]


def test_a_reference_is_one_however_it_is_written(prices):
    assert reference_key("5711/1A-010") == reference_key("5711 1a 010") == "57111A010"
    assert reference_key("311.30.42.30.01.005") == "31130423001005"

    prices.saw([offer("/a", reference="5711/1A-010"), offer("/b", reference="5711 1a 010")])

    assert {row["reference"] for row in kept(prices)} == {"57111A010"}


def test_the_offers_outlive_the_process(tmp_path):
    first = Prices(tmp_path / "prices.sqlite3")
    first.saw([offer()])
    first.close()

    assert len(kept(Prices(tmp_path / "prices.sqlite3"))) == 1


class Shop:
    """A shop as the monitor sees one after a scan: one known offer listed, nothing new."""

    def __init__(self, key):
        self.config = SITE_CONFIGS[key]
        self.last_scan = [offer(shop=key)]
        self.seen_ids = set()

    async def scrape(self):
        return []


@pytest.fixture
def monitor(prices):
    monitor = WatchMonitor(log_level="ERROR")
    monitor.prices = prices
    monitor.persistence = Mock()
    monitor.notification_manager = AsyncMock()
    return monitor


async def test_a_scan_remembers_every_listed_offer_not_only_the_new(monitor, prices):
    await monitor._scrape_single_site("worldoftime", Shop("worldoftime"), ScrapingSession("test"))

    assert [(row["site_key"], row["price"]) for row in kept(prices)] == [("worldoftime", 11550.0)]


async def test_a_shop_outside_the_eu_is_not_a_price_to_compare_with(monitor, prices):
    await monitor._scrape_single_site("tropicalwatch", Shop("tropicalwatch"), ScrapingSession("test"))

    assert kept(prices) == []


async def test_a_scraper_lists_every_watch_its_scan_found_and_none_after_a_failed_one():
    page = (Path(__file__).parent / "pages" / "kleinanzeigen.html").read_text(encoding="utf-8")
    source = replace(SITE_CONFIGS["worldoftime"], key="kleinanzeigen", url="https://example.test/")
    scraper = KleinanzeigenScraper(source, None, logging.getLogger("test"))

    with patch("scrapers.base.fetch_page", AsyncMock(return_value=page)):
        new = await scraper.scrape()
        assert new and scraper.last_scan == new

        assert await scraper.scrape() == []  # nothing new, and every offer still listed
        assert [watch.url for watch in scraper.last_scan] == [watch.url for watch in new]

    with patch("scrapers.base.fetch_page", AsyncMock(return_value=None)):
        await scraper.scrape()

    assert scraper.last_scan == []
