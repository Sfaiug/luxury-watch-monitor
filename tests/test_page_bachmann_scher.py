"""Bachmann & Scher's scraper reads saved copies of the shop's real listing and watch pages."""

import asyncio
import logging
from decimal import Decimal
from pathlib import Path

from bs4 import BeautifulSoup

from config import SITE_CONFIGS
from models import WatchData
from monitor import SCRAPER_CLASSES

PAGES = Path(__file__).parent / "pages"


def watch_from_page(name, title=""):
    """A watch, listed under `title`, after the scraper has read tests/pages/<name>.html as its own page."""
    config = SITE_CONFIGS["bachmann_scher"]
    scraper = SCRAPER_CLASSES["bachmann_scher"](config, None, logging.getLogger("test"))
    watch = WatchData(
        title=title,
        url=f"{config.base_url}/gebrauchte-luxusuhren-kaufen/a-watch-1.html",
        site_name=config.name,
        site_key=config.key,
    )
    page = (PAGES / f"{name}.html").read_text(encoding="utf-8")
    asyncio.run(scraper._extract_watch_details(watch, BeautifulSoup(page, "lxml")))
    return watch


def test_the_listing_gives_the_watches_one_can_buy(listed_watches):
    watches = listed_watches("bachmann_scher")

    # The page has 28 cards: 6 still reserved for B&S PLUS members and 10 sold
    assert len(watches) == 12
    assert all(watch.price for watch in watches)
    cartier = watches[0]
    assert cartier.brand == "Cartier"
    assert cartier.title == (
        "CARTIER Vintage SANTOS DUMONT LADY Paris Dail Ref 96062 18K Yelow Gold Bj-1990"
    )
    assert cartier.price == Decimal("8590")
    assert cartier.url == (
        "https://www.bachmann-scher.de/gebrauchte-luxusuhren-kaufen/"
        "cartier-vintage-santos-dumont-lady-paris-dail-ref-96062-18k-yelow-gold-bj-1990-17447.html"
    )
    assert cartier.image_url.startswith("https://www.bachmann-scher.de/fileadmin/")


def test_a_watch_page_gives_what_the_alert_shows():
    cartier = watch_from_page("bachmann_scher_watch")

    assert cartier.model == "Santos Dumont Lady"
    assert cartier.reference == "96062"
    assert cartier.year == "1990"
    assert cartier.condition == "★★★★☆"  # "Sehr gut"
    assert cartier.case_material == "Gelbgold"
    assert cartier.diameter == "23 x 23 mm"
    # Neither the page's rows nor the title name box or papers: the shop says nothing
    assert (cartier.has_box, cartier.has_papers) == (None, None)
    assert len(cartier.image_urls) >= 3


def test_a_box_named_only_in_the_title_is_a_box():
    """The Vendome's page has no "Mit Box" row, though the shop writes "It comes with its box"."""
    vendome = watch_from_page(
        "bachmann_scher_watch_box_in_title",
        title="CARTIER Vintage VENDOME Automatic Ref 17003 18K White Gold Folding Clasp Box Bj-1977 Exellent Very Rare Find",
    )

    assert (vendome.has_box, vendome.has_papers) == (True, None)


def test_a_full_set_shows_box_and_papers():
    bell_ross = watch_from_page("bachmann_scher_watch_full_set")

    assert (bell_ross.has_box, bell_ross.has_papers) == (True, True)
    assert bell_ross.condition == "★★★★★"  # "Ungetragen"


def test_every_shop_has_its_scraper_and_every_scraper_its_shop():
    assert set(SCRAPER_CLASSES) == set(SITE_CONFIGS)
