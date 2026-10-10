"""What a watch is offered for on Chrono24 inside the EU, read from its real search page."""

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

import chrono24
from chrono24 import NotResults, read, search_url

PAGES = Path(__file__).parent / "pages"
SEEN = datetime(2026, 10, 10, 11, 0)


def page(name):
    return (PAGES / name).read_text(encoding="utf-8")


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
