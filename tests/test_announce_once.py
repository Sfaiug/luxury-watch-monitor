"""Which of a shop's listed watches are announced."""

import logging
from decimal import Decimal
from unittest.mock import patch

import persistence
from models import WatchData
from persistence import SeenIds
from scrapers.base import BaseScraper


class Shop(BaseScraper):
    """A shop whose listing page is whatever the test says it is."""

    listed = []

    async def _extract_watches(self, soup):
        return list(self.listed)


def watch(path, price="5000"):
    return WatchData(
        title="Rolex Datejust",
        url=f"https://example.com{path}",
        site_name="Test Site",
        site_key="test_site",
        price=Decimal(price),
    )


async def scan(shop, *listed):
    shop.listed = listed
    with patch("scrapers.base.fetch_page", return_value="<html></html>"), patch(
        "scrapers.base.APP_CONFIG"
    ) as app_config:
        app_config.enable_detail_scraping = False
        return [w.url for w in await shop.scrape()]


async def test_a_listed_watch_is_announced_once_and_again_at_a_new_price(test_site_config):
    shop = Shop(test_site_config, None, logging.getLogger("test"))
    a, b, c = (f"https://example.com/watches/{name}" for name in "abc")

    # A shop with nothing remembered (new, or reset to test it) announces all it lists
    assert await scan(shop, watch("/watches/a"), watch("/watches/b")) == [a, b]
    assert await scan(shop, watch("/watches/a"), watch("/watches/b")) == []
    assert await scan(shop, watch("/watches/c"), watch("/watches/a")) == [c]
    # Still listed, and listed again after a gap: announced once
    assert await scan(shop, watch("/watches/c")) == []
    assert await scan(shop, watch("/watches/b"), watch("/watches/c")) == []
    # A new price is news
    assert await scan(shop, watch("/watches/b", price="4500")) == [b]


async def test_a_link_that_changes_with_the_page_is_the_same_listing(test_site_config):
    shop = Shop(test_site_config, None, logging.getLogger("test"))

    await scan(shop, watch("/watches/a?surroundingwotids=B,C"))

    assert await scan(shop, watch("/watches/a?surroundingwotids=C,D,E")) == []


async def test_a_watch_remembered_under_its_former_id_is_not_announced_again(test_site_config):
    shop = Shop(test_site_config, None, logging.getLogger("test"))
    a, b = watch("/watches/a"), watch("/watches/b")
    shop.set_seen_ids({a.former_id})  # announced before the ids changed

    # A page without listings changes nothing
    assert await scan(shop) == []
    assert await scan(shop, a, b) == ["https://example.com/watches/b"]
    assert await scan(shop, a, b) == []
    # Its new price is still news
    assert await scan(shop, watch("/watches/a", price="4500")) == [
        "https://example.com/watches/a"
    ]


async def test_a_former_id_vouches_for_one_listing(test_site_config):
    """An identical watch listed anew at the same price, after the first one sold, is news."""

    def datejust(number):
        return WatchData(
            title="Rolex Datejust",
            url=f"https://example.com/watches/datejust/{number}",
            site_name="Test Site",
            site_key="test_site",
            brand="Rolex",
            model="Datejust",
            reference="16234",
            price=Decimal("6900"),
        )

    shop = Shop(test_site_config, None, logging.getLogger("test"))
    remembered = {datejust(1).former_id}  # the former id has no link in it
    shop.set_seen_ids(remembered)

    assert await scan(shop, datejust(1)) == []
    assert datejust(1).former_id not in remembered
    assert await scan(shop, datejust(2)) == ["https://example.com/watches/datejust/2"]


def test_the_former_id_is_the_one_the_server_remembers():
    """Two ids as the code before this change made them."""
    hashed = WatchData(
        title="Rolex Datejust",
        url="https://www.grimmeissen.de/de/uhren/rolex/datejust/1017001",
        site_name="Grimmeissen",
        site_key="grimmeissen",
        brand="Rolex",
        model="Datejust",
        reference="16234",
        year="1995",
        price=Decimal("6900"),
        case_material="Stahl",
    )
    by_link = WatchData(
        title="Unknown Watch",
        url="https://www.juwelier-exchange.de/uhren/herrenuhren/978973/herrenuhr-rolex-gmt-master-ii-automatik",
        site_name="Juwelier Exchange",
        site_key="juwelier_exchange",
        price=Decimal("15750"),
    )

    assert hashed.former_id == "1db30a63397ba5f2636170d6d4563843"
    assert by_link.former_id == "1cface00f8114163f5a3ba58f3b852ee"


async def test_a_full_memory_forgets_the_watches_not_listed_for_longest(
    test_site_config, test_persistence_manager, monkeypatch
):
    monkeypatch.setattr(persistence.APP_CONFIG, "max_seen_items_per_site", 3)
    shop = Shop(test_site_config, None, logging.getLogger("test"))
    remembered = SeenIds()
    shop.set_seen_ids(remembered)
    a, b, c, d = (watch(f"/watches/{name}") for name in "abcd")

    # "a" was listed first and stays listed while "b" and "c" come and go
    await scan(shop, a)
    await scan(shop, a, b)
    await scan(shop, a, c)
    await scan(shop, a, d)
    test_persistence_manager.save_seen_items({"test_site": remembered})

    # Room for three: "b", not listed for longest, is forgotten, in the
    # memory the shop goes on with and in the file alike
    assert list(remembered) == [c.composite_id, a.composite_id, d.composite_id]
    assert list(test_persistence_manager.load_seen_items()["test_site"]) == list(remembered)
    assert await scan(shop, a, d) == []
