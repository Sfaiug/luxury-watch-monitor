"""A member's filter: kept in a file, scanned like a shop, announced in its own channel."""

import json
from dataclasses import asdict
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from filters import Filter, FilterStore
from monitor import WatchMonitor

RESULT_PAGE = (Path(__file__).parent / "pages" / "kleinanzeigen.html").read_text(
    encoding="utf-8"
)
SUBMARINER = Filter(
    channel_id="111",
    user_id="42",
    store="kleinanzeigen",
    seller="private",
    words="Rolex Submariner",
    min_price=5000,
    max_price=9000,
)


def test_filters_outlive_the_process(tmp_path):
    store = FilterStore(tmp_path / "filters.json")
    assert store.all() == []

    store.add(SUBMARINER)
    store.add(Filter("222", "42", "kleinanzeigen", "any", "Omega Speedmaster"))

    assert FilterStore(tmp_path / "filters.json").all()[0] == SUBMARINER

    store.remove("111")

    assert [f.channel_id for f in FilterStore(tmp_path / "filters.json").all()] == ["222"]


def test_a_filter_searches_its_marketplace():
    assert SUBMARINER.search_url == (
        "https://www.kleinanzeigen.de/s-uhren-schmuck/anzeige:angebote/"
        "anbieter:privat/preis:5000:9000/rolex-submariner/k0c157"
    )


@pytest.fixture
def monitor(tmp_path):
    monitor = WatchMonitor(log_level="ERROR")
    monitor.filter_store = FilterStore(tmp_path / "filters.json")
    monitor.session = AsyncMock()
    monitor.persistence = Mock()
    monitor.notification_manager = AsyncMock()
    monitor.notification_manager.send_notifications.side_effect = (
        lambda watches, source: len(watches)
    )
    return monitor


async def cycle(monitor, page=RESULT_PAGE):
    """Run one monitoring cycle with every fetched page being `page`; what was announced, and where."""
    monitor.notification_manager.send_notifications.reset_mock()
    fetch = AsyncMock(return_value=page)
    with patch("scrapers.base.fetch_page", fetch):
        await monitor.run_monitoring_cycle()
    return [
        (source.discord_channel_id, [watch.title for watch in watches])
        for watches, source in (
            call.args for call in monitor.notification_manager.send_notifications.call_args_list
        )
    ], [call.args[1] for call in fetch.call_args_list]


async def test_a_filter_s_matches_go_to_its_channel_from_the_first_scan(monitor):
    monitor.filter_store.add(SUBMARINER)

    announced, fetched = await cycle(monitor)

    assert fetched == [SUBMARINER.search_url]  # the search page and no offer's own page
    assert [channel for channel, _ in announced] == ["111"]
    titles = announced[0][1]
    assert len(titles) == 10 and titles[2] == "Rolex Submariner Date aus 2008"

    announced, _ = await cycle(monitor)

    assert announced == []  # each offer once


async def test_a_restart_announces_nothing_again(monitor, tmp_path):
    monitor.filter_store.add(SUBMARINER)
    await cycle(monitor)

    restarted = WatchMonitor(log_level="ERROR")
    restarted.filter_store = FilterStore(tmp_path / "filters.json")
    restarted.session = AsyncMock()
    restarted.persistence = Mock()
    restarted.notification_manager = AsyncMock()
    restarted.seen_items = monitor.seen_items  # as loaded from the file of remembered listings
    announced, fetched = await cycle(restarted)

    assert fetched == [SUBMARINER.search_url]
    assert announced == []


def a_shop(monitor):
    """A shop beside the filters; its scrape counts the scans."""
    shop = Mock(seen_ids=set(), scrape=AsyncMock(return_value=[]))
    monitor.scrapers["worldoftime"] = shop
    return shop.scrape


async def test_filters_that_cannot_be_read_do_not_stop_the_shops(monitor, tmp_path):
    shop_scans = a_shop(monitor)
    monitor.filter_store.add(SUBMARINER)
    await cycle(monitor)
    (tmp_path / "filters.json").write_text("not json", encoding="utf-8")

    _, fetched = await cycle(monitor)

    assert shop_scans.await_count == 2
    assert fetched == [SUBMARINER.search_url]  # the filter is scanned as last read


@pytest.mark.parametrize("store, seller", [("ebay", "any"), ("kleinanzeigen", "privat")])
async def test_a_filter_that_cannot_be_searched_stops_nothing_else(monitor, tmp_path, store, seller):
    """A marketplace or seller this version does not know, as after a rollback."""
    shop_scans = a_shop(monitor)
    monitor.logger = Mock()
    unknown = {"channel_id": "1", "user_id": "42", "store": store, "seller": seller, "words": "rolex"}
    (tmp_path / "filters.json").write_text(json.dumps([unknown, asdict(SUBMARINER)]), encoding="utf-8")

    for _ in range(2):
        _, fetched = await cycle(monitor)

        assert fetched == [SUBMARINER.search_url]  # the filter beside it is scanned
    assert shop_scans.await_count == 2
    assert monitor.logger.error.call_count == 1  # said once, not every cycle


async def test_a_removed_filter_is_no_longer_scanned(monitor):
    monitor.filter_store.add(SUBMARINER)
    await cycle(monitor)

    monitor.filter_store.remove("111")
    _, fetched = await cycle(monitor)

    assert fetched == []
    assert "filter:111" not in monitor.scrapers
    assert "filter:111" not in monitor.seen_items
