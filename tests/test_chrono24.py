"""What the watches the shops offer are offered for on Chrono24 inside the EU, read from its real search page."""

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

import chrono24
from chrono24 import NotResults, read, search_round, search_url
from models import ScrapingSession, WatchData
from monitor import WatchMonitor
from prices import Prices

PAGES = Path(__file__).parent / "pages"
SEEN = datetime(2026, 10, 10, 11, 0)


def page(name):
    return (PAGES / name).read_text(encoding="utf-8")


def shop_offer(reference, brand="Rolex"):
    return WatchData(
        title=f"{brand} {reference}",
        url=f"https://shop.example/{reference}",
        site_name="World of Time",
        site_key="worldoftime",
        brand=brand,
        reference=reference,
        price=Decimal("9000"),
        scraped_at=SEEN - timedelta(days=30),
    )


class Chrome:
    """Chrono24 behind a stand-in for Chrome: each search answers with the page given for its words."""

    def __init__(self, pages):
        self.pages = pages
        self.asked = []
        self.open = False

    async def __aenter__(self):
        self.open = True
        return self

    async def __aexit__(self, *exc):
        self.open = False

    async def page(self, url):
        assert self.open
        words = parse_qs(urlsplit(url).query)["query"][0]
        self.asked.append(words)
        return page(self.pages[words])


@pytest.fixture
def prices(tmp_path):
    return Prices(tmp_path / "prices.sqlite3")


@pytest.fixture(autouse=True)
def no_pause(monkeypatch):
    monkeypatch.setattr(chrono24, "PAUSE", 0)


def test_a_search_reads_how_many_offers_it_found_and_the_ones_on_its_page():
    found, offers = read(page("chrono24.html"), "Rolex", "116610LN", SEEN)

    assert found == 192
    assert len(offers) == 120
    first = offers[0]
    assert (first.url, first.title, first.model, first.brand, first.reference) == (
        "https://www.chrono24.de/rolex/rolex-submariner-date--id49103365.htm",
        "Rolex Submariner Date 116610LN 40 mm 3135 Keramik Ceramics",
        "Rolex Submariner Date",
        "Rolex",
        "116610LN",
    )
    assert (first.price, first.currency, first.site_key, first.scraped_at) == (Decimal("9189"), "EUR", "chrono24", SEEN)
    shown = [offer.price for offer in offers]
    assert shown == sorted(shown)  # cheapest first


def test_a_search_that_finds_nothing_reads_as_no_offers():
    assert read(page("chrono24_none.html"), "Zqxw", "99999XYZQ", SEEN) == (0, [])


def test_cloudflare_s_human_check_is_no_search_result():
    with pytest.raises(NotResults, match="Nur einen Moment"):
        read(page("chrono24_human_check.html"), "Rolex", "116610LN", SEEN)


def test_the_search_asks_for_the_offers_inside_the_eu_cheapest_first():
    asked = parse_qs(urlsplit(search_url("Patek Philippe", "57111A010")).query)

    assert asked["query"] == ["Patek Philippe 57111A010"]
    assert asked["countryIds"] == list(chrono24.EU)
    assert {"DE", "FR", "IT", "AT"} <= set(asked["countryIds"])
    assert not {"CH", "GB", "US", "HK", "JP"} & set(asked["countryIds"])
    assert (asked["currencyId"], asked["sortorder"], asked["pageSize"]) == (["EUR"], ["1"], ["120"])
    assert parse_qs(urlsplit(search_url(None, "116610LN")).query)["query"] == ["116610LN"]


async def test_a_reference_the_shops_offer_is_searched_and_its_eu_offers_kept(prices):
    prices.saw([shop_offer("116610LN")])
    chrome = Chrome({"Rolex 116610LN": "chrono24.html"})

    assert await search_round(prices, chrome, now=lambda: SEEN) == 1

    assert chrome.asked == ["Rolex 116610LN"]
    assert not chrome.open
    assert prices._db.execute(
        "SELECT COUNT(*), MIN(price), MIN(reference), MIN(first_seen) FROM offers WHERE site_key = 'chrono24'"
    ).fetchone() == (120, 9189.0, "116610LN", "2026-10-10T11:00:00")
    assert prices._db.execute("SELECT * FROM searches").fetchall() == [("116610LN", 192, "2026-10-10T11:00:00")]


async def test_a_reference_is_searched_again_once_its_offers_are_a_week_old(prices):
    prices.saw([shop_offer("116610LN")])
    pages = {"Rolex 116610LN": "chrono24.html"}
    await search_round(prices, Chrome(pages), now=lambda: SEEN)

    within_the_week = Chrome(pages)
    assert await search_round(prices, within_the_week, now=lambda: SEEN + timedelta(days=6, hours=23)) == 0
    assert within_the_week.asked == []

    a_week_on = Chrome(pages)
    assert await search_round(prices, a_week_on, now=lambda: SEEN + timedelta(days=7, seconds=1)) == 1
    assert a_week_on.asked == ["Rolex 116610LN"]


async def test_references_never_searched_come_before_the_ones_searched_longest_ago(prices):
    prices.saw([shop_offer("116610LN"), shop_offer("126610LN")])
    prices.searched("116610LN", 192, SEEN - timedelta(days=9))
    prices.searched("126610LN", 309, SEEN - timedelta(days=8))
    prices.saw([shop_offer("5711/1A-010", brand="Patek Philippe")])

    assert prices.due(SEEN - chrono24.FRESH, 20) == [
        ("Patek Philippe", "57111A010"),
        ("Rolex", "116610LN"),
        ("Rolex", "126610LN"),
    ]


async def test_a_page_that_is_no_search_result_ends_the_round_and_leaves_its_reference_due(prices):
    prices.saw([shop_offer("116610LN"), shop_offer("126610LN")])
    chrome = Chrome({"Rolex 116610LN": "chrono24_human_check.html"})

    with pytest.raises(NotResults):
        await search_round(prices, chrome, now=lambda: SEEN)

    assert chrome.asked == ["Rolex 116610LN"]
    assert not chrome.open
    assert prices._db.execute("SELECT COUNT(*) FROM offers WHERE site_key = 'chrono24'").fetchone() == (0,)
    assert prices.due(SEEN, 20) == [("Rolex", "116610LN"), ("Rolex", "126610LN")]


async def test_the_search_runs_beside_the_monitor_and_stops_with_it(monkeypatch, prices):
    states = []

    async def keep_up(kept_in, logger):
        assert kept_in is prices
        states.append("running")
        try:
            await asyncio.Event().wait()
        finally:
            states.append("stopped")

    monkeypatch.setattr(chrono24, "keep_up", keep_up)
    monitor = WatchMonitor()
    monitor.prices = prices

    async def one_cycle():
        await asyncio.sleep(0)
        monitor.shutdown_event.set()
        return ScrapingSession(session_id="test")

    monitor.run_monitoring_cycle = one_cycle

    assert await monitor.run_continuous() is False
    assert states == ["running", "stopped"]
