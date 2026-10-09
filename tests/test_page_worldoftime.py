"""World of Time's scraper reads a saved copy of the shop's real new-arrivals page."""

import asyncio
import logging
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch

from config import SITE_CONFIGS
from monitor import SCRAPER_CLASSES


def test_every_priced_watch_has_its_price(listed_watches):
    watches = listed_watches("worldoftime")

    # The eight newest in the section on top, sixteen in the list below it;
    # one of the 24, the Aquanaut 5167A-001, shows "Sold" in place of its price
    assert len(watches) == 23
    assert "5167A-001" not in [w.reference for w in watches]
    assert all(w.price for w in watches)
    datejust = watches[8]
    assert (datejust.title, datejust.reference) == ("Rolex Datejust", "16014")
    assert datejust.price == Decimal("6250")
    assert datejust.price_display == "€6.250"


def test_the_newest_watches_are_read(listed_watches):
    newest = listed_watches("worldoftime")[0]

    assert newest.title == "Audemars Piguet Royal Oak"
    assert newest.reference == "25860ST.O.1110ST.03"
    assert newest.price == Decimal("31500")  # "€ 31,500,-"
    assert newest.year == "2000"
    assert newest.url.endswith("/Watches/audemars-piguet/royal-oak-D1B2B40")


def test_a_new_watch_s_own_page_is_not_fetched(listed_watches):
    """Everything the alert shows is on the listing page."""
    scraper = SCRAPER_CLASSES["worldoftime"](
        SITE_CONFIGS["worldoftime"], None, logging.getLogger("test")
    )
    page = (Path(__file__).parent / "pages" / "worldoftime.html").read_text(encoding="utf-8")
    fetch = AsyncMock(return_value=page)

    with patch("scrapers.base.fetch_page", fetch):
        announced = asyncio.run(scraper.scrape())

    assert len(announced) == len(listed_watches("worldoftime")) > 0
    assert fetch.call_count == 1


def test_a_two_word_brand_is_the_brand(listed_watches):
    carrera = next(w for w in listed_watches("worldoftime") if w.title.startswith("TAG HEUER Carrera"))

    assert (carrera.brand, carrera.model) == ("TAG Heuer", "Carrera")
