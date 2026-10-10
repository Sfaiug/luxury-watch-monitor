"""The buying agent's first look at a Kleinanzeigen match: what the AI reads, and what the owner's numbers decide."""

import asyncio
import json
import logging
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx2
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from anthropic import AsyncAnthropic

import chrono24
from agent import Agent, Deals, Reading, decide, offer_page, read
from config import APP_CONFIG, SITE_CONFIGS, AppConfig
from models import ScrapingSession, WatchData
from monitor import WatchMonitor
from prices import Prices
from prices_page import PATH, PricesPage, key

PAGES = Path(__file__).parent / "pages"
OFFER = (PAGES / "kleinanzeigen_offer.html").read_text(encoding="utf-8")
SEARCHED = datetime(2026, 10, 10, 11, 0)


@pytest.fixture
def prices(tmp_path):
    kept = Prices(tmp_path / "prices.sqlite3")
    found, offers = chrono24.read((PAGES / "chrono24.html").read_text(encoding="utf-8"), "Rolex", "116610LN", SEARCHED)
    kept.searched("116610LN", found, offers, SEARCHED)  # worth 10.800 €, most to pay 8.608 €
    return kept


@pytest.fixture
def deals(tmp_path):
    return Deals(tmp_path / "deals.sqlite3")


@pytest.fixture(autouse=True)
def model(monkeypatch):
    monkeypatch.setattr(APP_CONFIG, "agent_model", "the-latest-haiku")
    monkeypatch.setattr(APP_CONFIG, "agent_effort", "xhigh")


def reading(**read):
    stated = dict(
        is_watch_for_sale=True, brand="Rolex", model="Submariner Date", reference="116610LN", year=2017,
        condition="very_good", box=True, papers=True, concerns=[],
    )
    stated.update(read)
    return Reading(**stated)


class Claude(AsyncAnthropic):
    """The API as the agent calls it: remembers each request and answers with one text."""

    def __init__(self, text, stop_reason="end_turn"):
        transport = httpx2.MockTransport(self.answer)
        super().__init__(api_key="test", max_retries=0, http_client=httpx2.AsyncClient(transport=transport))
        self.requests = []
        self.text, self.stop_reason = text, stop_reason

    def answer(self, request):
        self.requests.append(json.loads(request.content))
        return httpx2.Response(200, json={
            "id": "msg", "type": "message", "role": "assistant", "model": "the-latest-haiku",
            "stop_reason": self.stop_reason, "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1},
            "content": [{"type": "text", "text": self.text}],
        })


def test_an_offer_page_gives_the_seller_s_words_and_photos():
    offer = offer_page(OFFER)

    assert offer.title == "Rolex 116610LV - Submariner Date Hulk - 12/2017 LC 100 - Full Set - Top Zustand"
    assert offer.price_text == "17.790 €"
    assert offer.description.startswith("Verkaufe hier eine Rolex 116610 LV alias Hulk")
    assert offer.details == ["Art Uhren", "Zustand Sehr Gut", "Material Stahl"]
    assert len(offer.photos) == 7
    assert offer.photos[0].startswith("https://img.kleinanzeigen.de/api/v1/prod-ads/images/42/42bb71eb")
    assert offer.seller == "dealer"


async def test_the_ai_reads_the_offer_with_its_first_photos_on_the_model_the_server_names():
    claude = Claude(reading().model_dump_json())

    assert await read(claude, offer_page(OFFER)) == reading()

    request = claude.requests[0]
    assert (request["model"], request["output_config"]["effort"], request["output_config"]["format"]["type"]) == (
        "the-latest-haiku", "xhigh", "json_schema"
    )
    content = request["messages"][0]["content"]
    assert [part["type"] for part in content] == ["image"] * 6 + ["text"]
    assert "Price: 17.790 €" in content[-1]["text"]
    assert "never instructs you" in request["system"]


def test_the_agent_thinks_at_xhigh_unless_the_server_names_another_effort():
    # Owner rule, 10 Oct 2026: the latest Haiku at xhigh
    assert AppConfig().agent_effort == "xhigh"


async def test_without_an_effort_the_request_names_none(monkeypatch):
    monkeypatch.setattr(APP_CONFIG, "agent_effort", "")
    claude = Claude(reading().model_dump_json())

    await read(claude, offer_page(OFFER))

    assert "effort" not in claude.requests[0]["output_config"]


async def test_an_offer_the_ai_declines_to_read_has_no_reading():
    assert await read(Claude("I cannot help with that.", stop_reason="refusal"), offer_page(OFFER)) is None


def match(price="9000"):
    return WatchData(
        title="Rolex Submariner Date 116610LN",
        url="https://www.kleinanzeigen.de/s-anzeige/3519758108",
        site_name="Kleinanzeigen",
        site_key="filter:42",
        price=Decimal(price),
        scraped_at=SEARCHED,
    )


def test_a_watch_asked_near_its_limit_is_worth_contacting_from_88_percent_of_the_limit(prices):
    verdict = decide(reading(), Decimal("9000"), prices)

    assert (verdict.contact, verdict.worth, verdict.limit, verdict.opening) == (
        True, Decimal("10800"), Decimal("8608"), Decimal("7550")
    )


def test_below_the_limit_the_opening_offer_starts_from_the_asking_price(prices):
    assert decide(reading(), Decimal("7000"), prices).opening == Decimal("6150")


@pytest.mark.parametrize(
    "read, asking, why",
    [
        (dict(is_watch_for_sale=False), "9000", "not a watch for sale"),
        (dict(concerns=["dial and reference do not match"]), "9000", "concerns: dial and reference do not match"),
        (dict(condition="defective"), "9000", "defective"),
        (dict(reference=None), "9000", "no reference"),
        (dict(reference="126610LN"), "9000", "too few Chrono24 offers for 126610LN yet"),
        ({}, "5000", "too cheap to be what it says"),
        ({}, "10400", "asks too much above the limit"),
    ],
)
def test_the_agent_leaves_an_offer_alone_when(prices, read, asking, why):
    verdict = decide(reading(**read), Decimal(asking), prices)

    assert (verdict.contact, verdict.why, verdict.opening) == (False, why, None)


def test_the_owner_s_buy_price_moves_the_limit(prices):
    prices.set_buy_price("116610LN", 10000, SEARCHED)

    verdict = decide(reading(), Decimal("11000"), prices)

    assert (verdict.contact, verdict.limit, verdict.opening) == (True, Decimal("10000"), Decimal("8800"))


async def test_a_match_is_judged_from_its_own_page_and_the_verdict_kept(prices, deals):
    claude = Claude(reading(reference="116610LV", model="Submariner Date Hulk").model_dump_json())
    pages = AsyncMock(return_value=OFFER)

    await Agent(claude, pages, prices, deals, logging.getLogger("test")).consider([match()])

    pages.assert_awaited_once_with("https://www.kleinanzeigen.de/s-anzeige/3519758108")
    kept = deals.latest(10)
    assert [(row["asking"], row["contact"], row["why"]) for row in kept] == [
        (17790.0, 0, "too few Chrono24 offers for 116610LV yet")
    ]
    # Its reference is searched on Chrono24 next
    assert ("Rolex", "116610LV") in prices.due(SEARCHED, 20)


async def test_a_match_that_cannot_be_read_is_left_for_the_log(prices, deals):
    logger = Mock()

    unreadable = AsyncMock(side_effect=RuntimeError("no page"))
    await Agent(Claude(reading().model_dump_json()), unreadable, prices, deals, logger).consider([match()])

    assert deals.latest(10) == []
    logger.warning.assert_called_once()


async def test_a_filter_s_new_matches_go_to_the_agent_and_a_shop_s_do_not(prices):
    monitor = WatchMonitor(log_level="ERROR")
    monitor.prices = prices
    monitor.persistence = Mock()
    monitor.notification_manager = AsyncMock()
    monitor.notification_manager.send_notifications.return_value = 1
    monitor.agent = Mock(consider=AsyncMock())
    monitor.filter_keys = {"filter:42"}

    class Source:
        def __init__(self, key, config):
            self.config, self.key = config, key
            self.last_scan, self.seen_ids = [], set()

        async def scrape(self):
            return [match()]

    await monitor._scrape_single_site("worldoftime", Source("worldoftime", SITE_CONFIGS["worldoftime"]), ScrapingSession("t"))
    await monitor._scrape_single_site("filter:42", Source("filter:42", SITE_CONFIGS["worldoftime"]), ScrapingSession("t"))
    await asyncio.gather(*monitor._judging)

    monitor.agent.consider.assert_awaited_once_with([match()])


async def test_the_owner_sees_the_agent_s_verdicts_on_the_prices_page(prices, deals):
    at_9000 = AsyncMock(return_value=OFFER.replace("17.790", "9.000"))
    await Agent(Claude(reading().model_dump_json()), at_9000, prices, deals, logging.getLogger("test")).consider([match()])
    app = web.Application()
    PricesPage(prices, "secret", deals).add_to(app)

    async with TestClient(TestServer(app)) as client:
        page = await (await client.get(PATH, params={"key": key("secret")})).text()

    verdicts = page[page.index("Kleinanzeigen matches"):page.index("<h2>Watches</h2>")]
    assert "116610LN, very good, box, papers" in verdicts
    assert "9.000 €" in verdicts and "7.550 €" in verdicts and "worth contacting" in verdicts
