"""Kleinanzeigen's reader on the first eight cards of a saved copy of a real search result page."""

import asyncio
import logging
from decimal import Decimal
from pathlib import Path

from bs4 import BeautifulSoup

from config import SiteConfig
from models import WatchData
from scrapers.kleinanzeigen import KleinanzeigenScraper, search_url
from utils import parse_year

SEARCH = "https://www.kleinanzeigen.de/s-uhren-schmuck/anzeige:angebote/"


def offers():
    config = SiteConfig(
        name="Kleinanzeigen",
        key="filter:1",
        url=search_url("Rolex Submariner", 5000, 9000),
        webhook_env_var="",
        color=0x86B817,
        base_url="https://www.kleinanzeigen.de",
    )
    scraper = KleinanzeigenScraper(config, None, logging.getLogger("test"))
    page = (Path(__file__).parent / "pages" / "kleinanzeigen.html").read_text(
        encoding="utf-8"
    )
    return asyncio.run(scraper._extract_watches(BeautifulSoup(page, "lxml")))


def test_the_search_address_lets_the_site_do_the_filtering():
    assert search_url("Rolex Submariner", 5000, 9000, "private") == (
        SEARCH + "anbieter:privat/preis:5000:9000/rolex-submariner/k0c157"
    )
    assert search_url("A. Lange & Söhne", min_price=20000, seller="dealer") == (
        SEARCH + "anbieter:gewerblich/preis:20000:/a.-lange-%26-s%C3%B6hne/k0c157"
    )
    assert search_url("omega speedmaster", max_price=3000) == (
        SEARCH + "preis::3000/omega-speedmaster/k0c157"
    )
    assert search_url("omega speedmaster") == SEARCH + "omega-speedmaster/k0c157"


def test_an_offer_is_read_like_a_shop_s_watch():
    watches = offers()

    assert len(watches) == 8
    submariner = watches[2]
    assert submariner.title == "Rolex Submariner Date aus 2008"
    assert submariner.url == (
        "https://www.kleinanzeigen.de/s-anzeige/rolex-submariner-date-aus-2008/3535014294-157-2057"
    )
    assert submariner.price == Decimal("8300")
    assert submariner.reference == "16610"  # "Ref.16610" in the description
    assert submariner.year == "2008"
    assert submariner.condition == "★★★☆☆"  # "Guter Zustand"
    assert (submariner.has_box, submariner.has_papers) == (True, True)  # "Fullset"
    assert submariner.image_url.startswith("https://img.kleinanzeigen.de/")
    assert all(watch.price for watch in watches)


def test_a_price_open_to_offers_says_so():
    assert offers()[3].price_display == "€8.490 VB"


def test_the_year_is_not_the_service_year():
    serviced = offers()[7]

    assert serviced.title.startswith("Rolex Submariner Date - 16800 - Service 2026 - 1981")
    assert serviced.year == "1981"
    assert parse_year("Rolex Submariner Date - 16800 - Service 2026 - 1981") == "1981"
    assert parse_year("Revision 2024, gekauft 2015") == "2015"


def test_an_offer_s_alert_has_a_shop_alert_s_structure():
    shop_watch = WatchData(
        title="Rolex Submariner Date",
        url="https://www.grimmeissen.de/de/uhren/rolex/submariner/1",
        site_name="Grimmeissen",
        site_key="grimmeissen",
        brand="Rolex",
        model="Submariner Date",
        reference="16610",
        year="2008",
        price=Decimal("8300"),
        condition="★★★☆☆",
        has_papers=True,
        has_box=True,
        image_url="https://www.grimmeissen.de/1.jpg",
    )
    shop, offer = shop_watch.to_discord_embed(0), offers()[2].to_discord_embed(0)

    assert list(offer) == list(shop)
    assert [field["name"] for field in offer["fields"]] == [
        field["name"] for field in shop["fields"]
    ]
    assert offer["title"] == "Rolex Submariner Date aus 2008 | 16610"
    assert offer["footer"]["text"].startswith("Kleinanzeigen - Detected: ")


def test_an_offer_without_a_reference_is_searched_by_its_title():
    untitled = offers()[4]

    assert untitled.reference is None
    assert "query=Rolex+Submariner+16613+Stahl+Gold" in untitled.chrono24_search_url
