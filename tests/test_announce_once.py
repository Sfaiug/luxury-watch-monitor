"""Which of a shop's listed watches are announced."""

import logging
from decimal import Decimal
from unittest.mock import patch

from models import WatchData
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


async def test_a_shop_announces_its_news_not_its_stock(test_site_config):
    shop = Shop(test_site_config, None, logging.getLogger("test"))
    a, b, c = (f"https://example.com/watches/{name}" for name in "abc")

    assert await scan(shop, watch("/watches/a"), watch("/watches/b")) == []
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
