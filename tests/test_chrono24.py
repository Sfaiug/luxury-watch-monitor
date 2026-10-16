"""What the watches the shops offer are offered for on Chrono24 inside the EU, read from its real search page."""

import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from bs4 import BeautifulSoup

import chrono24
from chrono24 import FULL_SET, KINDS, USED, NotResults, read, search_round, search_url
from models import ScrapingSession, WatchData
from monitor import WatchMonitor
from prices import Prices
from worth import buy_limit, worth

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
        asked = parse_qs(urlsplit(url).query)
        words = asked["query"][0]
        self.asked.append(words)
        html = page(self.pages[words])
        number = int(asked.get("showPage", ["1"])[0])
        if number > 1:
            soup = BeautifulSoup(html, "lxml")
            remaining = int(soup.find("strong").get_text().split()[0]) - (number - 1) * chrono24.PAGE
            for n, card in enumerate(soup.select(".js-listing-item-container")):
                if n >= remaining:
                    card.decompose()
                else:
                    link = card.select_one("a.js-listing-item-link")
                    link["href"] = link["href"].replace(".htm", f"-page{number}.htm")
                    card.select_one(".wt-listing-item-price").string = "12.000 €"
            html = str(soup)
        return html


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


@pytest.mark.parametrize("renamed", ["js-listing-item-container", "js-listing-item-link", "wt-listing-item-price"])
def test_cards_unread_when_chrono24_renames_a_class(renamed):
    html = page("chrono24.html").replace(renamed, renamed + "-changed")

    with pytest.raises(NotResults, match="could not read.*0 of 120"):
        read(html, "Rolex", "116610LN", SEEN)


@pytest.mark.parametrize(
    ("found", "readable", "failed"),
    [(192, 30, True), (4, 0, True), (4, 1, True), (192, 119, False), (4, 3, False), (4, 4, False), (0, 0, False)],
)
def test_cards_unread_are_compared_with_the_offers_expected_on_one_page(found, readable, failed):
    soup = BeautifulSoup(page("chrono24.html"), "lxml")
    soup.find("strong").string = f"{found} Inserate"
    for n, card in enumerate(soup.select(".js-listing-item-container")):
        if n >= found:
            card.decompose()
        elif n >= readable:
            card.select_one(".wt-listing-item-price").decompose()

    if failed:
        with pytest.raises(NotResults, match="could not read"):
            read(str(soup), "Rolex", "116610LN", SEEN)
    else:
        count, offers = read(str(soup), "Rolex", "116610LN", SEEN)
        assert (count, len(offers)) == (found, readable)


@pytest.mark.parametrize(("found", "on_request"), [(1, 1), (4, 4), (5, 1), (6, 5), (9, 4), (192, 100)])
def test_priced_offers_are_read_with_the_total_count_needed_for_pagination(found, on_request):
    # Live, 15 Oct 2026: the one full-set Patek Philippe 3416 asked "Preis auf Anfrage"
    soup = BeautifulSoup(page("chrono24.html"), "lxml")
    soup.find("strong").string = f"{found} Inserate"
    for n, card in enumerate(soup.select(".js-listing-item-container")):
        if n >= found:
            card.decompose()
        elif n < on_request:
            card.select_one(".wt-listing-item-price").string = "Preis auf Anfrage"

    count, offers = read(str(soup), "Patek Philippe", "3416", SEEN)

    assert (count, len(offers)) == (found, min(found, chrono24.PAGE) - on_request)


def test_cloudflare_s_human_check_is_no_search_result():
    with pytest.raises(NotResults, match="Nur einen Moment"):
        read(page("chrono24_human_check.html"), "Rolex", "116610LN", SEEN)


def test_the_search_asks_for_the_offers_inside_the_eu_vat_area_cheapest_first():
    asked = parse_qs(urlsplit(search_url("Patek Philippe", "57111A010", USED)).query)

    assert asked["query"] == ["Patek Philippe 57111A010"]
    # The 27 states and Monaco; not Martinique, Guadeloupe or Réunion, EU land outside its VAT
    assert sorted(asked["countryIds"]) == sorted(
        "AT BE BG CY CZ DE DK EE ES FI FR GR HR HU IE IT LT LU LV MT NL PL PT RO SE SI SK".split() + ["MC"]
    )
    assert (asked["currencyId"], asked["sortorder"], asked["pageSize"]) == (["EUR"], ["1"], ["120"])
    assert parse_qs(urlsplit(search_url(None, "116610LN", USED)).query)["query"] == ["116610LN"]


def test_the_search_asks_for_used_watches_and_for_used_ones_with_their_box_and_papers():
    used = parse_qs(urlsplit(search_url("Rolex", "116610LN", USED)).query)
    full_set = parse_qs(urlsplit(search_url("Rolex", "116610LN", FULL_SET)).query)

    assert (used["usedOrNew"], "specials" in used) == (["used"], False)
    # Chrono24's own "original box and papers", not its "original box" and "original papers", which find either
    assert (full_set["usedOrNew"], full_set["specials"]) == (["used"], ["102"])


async def test_a_reference_the_shops_offer_is_searched_for_each_kind_and_its_eu_offers_kept(prices):
    prices.saw([shop_offer("116610LN")])
    chrome = Chrome({"Rolex 116610LN": "chrono24.html"})

    assert await search_round(prices, chrome, now=lambda: SEEN) == 2

    assert chrome.asked == ["Rolex 116610LN"] * 4
    assert not chrome.open
    assert prices._db.execute(
        "SELECT COUNT(*), MIN(price), MIN(reference), MIN(first_seen) FROM offers WHERE site_key = 'chrono24'"
    ).fetchone() == (120, 9189.0, "116610LN", "2026-10-10T11:00:00")
    assert sorted(prices._db.execute("SELECT * FROM searches").fetchall()) == [
        ("116610LN", FULL_SET, 192, "2026-10-10T11:00:00"),
        ("116610LN", USED, 192, "2026-10-10T11:00:00"),
    ]
    assert [worth(prices, "116610LN", kind) for kind in KINDS] == [Decimal("10800")] * 2


async def test_a_reference_is_searched_again_around_the_clock_an_hour_on_at_the_earliest(prices):
    prices.saw([shop_offer("116610LN")])
    pages = {"Rolex 116610LN": "chrono24.html"}
    await search_round(prices, Chrome(pages), now=lambda: SEEN)

    within_the_hour = Chrome(pages)
    assert await search_round(prices, within_the_hour, now=lambda: SEEN + timedelta(minutes=59)) == 0
    assert within_the_hour.asked == []

    an_hour_on = Chrome(pages)
    assert await search_round(prices, an_hour_on, now=lambda: SEEN + timedelta(hours=1, seconds=1)) == 2
    assert an_hour_on.asked == ["Rolex 116610LN"] * 4


async def test_searches_never_made_come_before_the_ones_made_longest_ago(prices):
    prices.saw([shop_offer("116610LN"), shop_offer("126610LN")])
    for kind in KINDS:
        prices.searched("116610LN", kind, 192, [], SEEN - timedelta(days=9))
    prices.searched("126610LN", USED, 309, [], SEEN - timedelta(days=8))
    prices.saw([shop_offer("5711/1A-010", brand="Patek Philippe")])

    assert prices.due(list(KINDS), SEEN - chrono24.FRESH, 20) == [
        ("Rolex", "126610LN", FULL_SET),
        ("Patek Philippe", "57111A010", USED),
        ("Patek Philippe", "57111A010", FULL_SET),
        ("Rolex", "116610LN", USED),
        ("Rolex", "116610LN", FULL_SET),
        ("Rolex", "126610LN", USED),
    ]


async def test_a_reference_offered_since_its_last_search_goes_first_the_latest_offered_first(prices):
    prices.saw([shop_offer("116610LN"), shop_offer("126610LN"), shop_offer("5711/1A-010", brand="Patek Philippe")])
    # Chrono24's own offers, found by one kind's search, are no new offer for the other kind
    _, found = read(page("chrono24.html"), "Rolex", "116610LN", SEEN - timedelta(hours=29))
    prices.searched("116610LN", USED, 192, [], SEEN - timedelta(hours=30))
    prices.searched("116610LN", FULL_SET, 192, found, SEEN - timedelta(hours=29))
    for kind in KINDS:
        prices.searched("126610LN", kind, 309, [], SEEN - timedelta(hours=20))
    # A filter's match, just read by the agent, is priced before the rest
    match = shop_offer("126610LN")
    match.url, match.site_key, match.scraped_at = "https://www.kleinanzeigen.de/s-anzeige/1", "filter:42", SEEN
    prices.saw([match])

    assert prices.due(list(KINDS), SEEN - chrono24.FRESH, 20) == [
        ("Rolex", "126610LN", USED),
        ("Rolex", "126610LN", FULL_SET),
        ("Patek Philippe", "57111A010", USED),
        ("Patek Philippe", "57111A010", FULL_SET),
        ("Rolex", "116610LN", USED),
        ("Rolex", "116610LN", FULL_SET),
    ]


async def test_the_searches_made_before_they_asked_for_one_kind_are_made_again(tmp_path):
    before = Prices(tmp_path / "prices.sqlite3")
    before.saw([shop_offer("116610LN")])
    before._db.execute("DROP TABLE searches")  # as it was, new watches among the offers it counted
    before._db.execute("CREATE TABLE searches (reference TEXT PRIMARY KEY, found INTEGER NOT NULL, searched TEXT NOT NULL)")
    before._db.execute("INSERT INTO searches VALUES ('116610LN', 192, '2026-10-10T11:00:00')")
    before._db.execute("PRAGMA user_version = 1")
    before._db.commit()
    before.close()

    prices = Prices(tmp_path / "prices.sqlite3")
    assert prices.due(list(KINDS), SEEN - chrono24.FRESH, 20) == [("Rolex", "116610LN", USED), ("Rolex", "116610LN", FULL_SET)]

    # Made again, they stand for their hour
    for kind in KINDS:
        prices.searched("116610LN", kind, 192, [], SEEN)
    prices.close()
    assert Prices(tmp_path / "prices.sqlite3").due(list(KINDS), SEEN - chrono24.FRESH, 20) == []


async def test_a_page_that_is_no_search_result_ends_the_round_and_leaves_its_reference_due(prices):
    prices.saw([shop_offer("116610LN"), shop_offer("126610LN")])
    chrome = Chrome({"Rolex 116610LN": "chrono24_human_check.html"})

    with pytest.raises(NotResults):
        await search_round(prices, chrome, now=lambda: SEEN)

    assert chrome.asked == ["Rolex 116610LN"]
    assert not chrome.open
    assert prices._db.execute("SELECT COUNT(*) FROM offers WHERE site_key = 'chrono24'").fetchone() == (0,)
    assert prices.due(list(KINDS), SEEN, 20) == [
        ("Rolex", "116610LN", USED), ("Rolex", "116610LN", FULL_SET), ("Rolex", "126610LN", USED), ("Rolex", "126610LN", FULL_SET)
    ]


@pytest.mark.parametrize("unreadable", [120, 100])
@pytest.mark.parametrize("failed_page", [1, 2])
async def test_cards_unread_keep_the_last_good_offers_and_limit_leave_the_reference_due_and_log_it(prices, monkeypatch, caplog, unreadable, failed_page):
    prices.saw([shop_offer("116610LN")])
    pages = {"Rolex 116610LN": "chrono24.html"}
    last_good = datetime.now() - chrono24.FRESH - timedelta(seconds=1)
    await search_round(prices, Chrome(pages), now=lambda: last_good)
    kept = {
        table: prices._db.execute(f"SELECT * FROM {table}").fetchall()
        for table in ("offers", "searches", "searched_offers")
    }
    assert [buy_limit(prices, "116610LN", kind) for kind in KINDS] == [Decimal("8608")] * 2

    class ChangedChrome(Chrome):
        async def page(self, url):
            html = await super().page(url)
            number = int(parse_qs(urlsplit(url).query).get("showPage", ["1"])[0])
            return html.replace("wt-listing-item-price", "changed-price", unreadable) if number == failed_page else html

    chrome = ChangedChrome(pages)
    monkeypatch.setattr(chrono24, "Chrome", lambda ways: chrome)
    monkeypatch.setattr(chrono24.proxies, "for_browser", lambda path: [])

    async def stop_after_round(delay):
        if delay == chrono24.IDLE:
            raise asyncio.CancelledError
        assert delay == chrono24.PAUSE

    monkeypatch.setattr(chrono24.asyncio, "sleep", stop_after_round)
    with pytest.raises(asyncio.CancelledError):
        await chrono24.keep_up(prices, logging.getLogger(__name__))

    assert chrome.asked == ["Rolex 116610LN"] * failed_page
    assert not chrome.open
    for table, rows in kept.items():
        assert prices._db.execute(f"SELECT * FROM {table}").fetchall() == rows
    assert prices.due(list(KINDS), datetime.now() - chrono24.FRESH, 20) == [
        ("Rolex", "116610LN", USED), ("Rolex", "116610LN", FULL_SET)
    ]
    assert [buy_limit(prices, "116610LN", kind) for kind in KINDS] == [Decimal("8608")] * 2
    assert "Chrono24: searching stopped:" in caplog.text
    assert "could not read" in caplog.text
    expected = 120 if failed_page == 1 else 72
    assert f"{max(expected - unreadable, 0)} of {expected}" in caplog.text


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
