"""Kleinanzeigen's reader on ten cards from saved copies of two real search result pages."""

import asyncio
import logging
from decimal import Decimal
from pathlib import Path

from bs4 import BeautifulSoup

from config import SiteConfig
from models import WatchData
from scrapers.kleinanzeigen import KleinanzeigenScraper, search_url

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
    # A slash separates words like a space; in the address it would start a new part
    assert search_url("Rolex 16613 Stahl/Gold") == SEARCH + "rolex-16613-stahl-gold/k0c157"


def test_an_offer_is_read_like_a_shop_s_watch():
    watches = offers()

    assert len(watches) == 10
    submariner = watches[2]
    assert submariner.title == "Rolex Submariner Date aus 2008"
    assert submariner.url == (
        "https://www.kleinanzeigen.de/s-anzeige/rolex-submariner-date-aus-2008/3535014294-157-2057"
    )
    assert submariner.price == Decimal("8300")
    assert submariner.image_url.startswith("https://img.kleinanzeigen.de/")
    assert all(watch.price for watch in watches)


def test_a_price_open_to_offers_says_so():
    assert offers()[3].price_display == "€8.490 VB"


def test_the_price_is_the_one_to_pay():
    reduced, box = offers()[8:]

    # "1.699 € VB", then the old price struck through: "2.199 €"
    assert reduced.title.startswith("Vintage Omega Constellation Manhattan")
    assert reduced.price_display == "€1.699 VB"
    # The seller's text says "Versand zzgl 7€"
    assert (box.title, box.price) == ("OMEGA Uhrenbox neu", Decimal("100"))


def test_nothing_is_read_out_of_the_seller_s_own_words():
    dealer = offers()[0]

    # Its text says "Referenz: 16613", "Herstellungsjahr: ca. 1993" and
    # "Box/Papiere: Nicht vorhanden", and is cut off after a few lines
    assert dealer.title == "Rolex Submariner Date 16613 Bicolor 40mm"
    for watch in offers():
        assert (watch.reference, watch.year, watch.condition) == (None, None, None)
        assert (watch.has_box, watch.has_papers) == (None, None)


def test_an_offer_s_alert_has_a_shop_alert_s_structure():
    shop_watch = WatchData(
        title="Rolex Submariner Date",
        url="https://www.grimmeissen.de/de/uhren/rolex/submariner/1",
        site_name="Grimmeissen",
        site_key="grimmeissen",
        price=Decimal("8300"),
        image_url="https://www.grimmeissen.de/1.jpg",
    )
    shop, offer = shop_watch.to_discord_embed(0), offers()[2].to_discord_embed(0)

    assert list(offer) == list(shop)
    assert [field["name"] for field in offer["fields"]] == [
        field["name"] for field in shop["fields"]
    ]
    assert offer["footer"]["text"].startswith("Kleinanzeigen - Detected: ")


def test_the_alert_is_headed_by_the_seller_s_title_whole():
    assert offers()[2].to_discord_embed(0)["title"] == "Rolex Submariner Date aus 2008"
    # A title's last word is part of it: a "Submariner Date" is not a "Submariner"
    ending_in_date = WatchData(
        title="Rolex Submariner Date",
        url="https://www.kleinanzeigen.de/s-anzeige/rolex-submariner-date/1-157-1",
        site_name="Kleinanzeigen",
        site_key="filter:1",
    )
    assert ending_in_date.to_discord_embed(0)["title"] == "Rolex Submariner Date"


def test_an_offer_is_searched_on_chrono24_by_its_title():
    assert "query=Rolex+Submariner+Date+aus+2008" in offers()[2].chrono24_search_url


def test_an_offer_without_a_picture_is_read_too():
    # A real card of 9 October: no picture, so no JSON-LD block
    card = (
        "<article data-adid=3527434489 data-href=/s-anzeige/vacheron-constantin-overseas/3527434489-157-9342>"
        "<div data-image-container><svg data-title=cameraDisabled></svg></div>"
        "<h3><a href=/s-anzeige/vacheron-constantin-overseas/3527434489-157-9342>"
        "Vacheron Constantin Overseas 4000V/210A-B911 Box + Papiere Moonp</a></h3>"
        "<p class=text-title3>44.990 €</p></article>"
    )
    scraper = KleinanzeigenScraper(
        SiteConfig(name="Kleinanzeigen", key="filter:1", url="", webhook_env_var="", color=0,
                   base_url="https://www.kleinanzeigen.de"),
        None,
        logging.getLogger("test"),
    )

    (watch,) = asyncio.run(scraper._extract_watches(BeautifulSoup(card, "lxml")))

    assert watch.title == "Vacheron Constantin Overseas 4000V/210A-B911 Box + Papiere Moonp"
    assert (watch.price_display, watch.image_url) == ("€44.990", None)
