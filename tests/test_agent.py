"""The buying agent's first look at a Kleinanzeigen match: what the AI reads, and what the owner's numbers decide."""

import asyncio
import json
import logging
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx2
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from anthropic import AsyncAnthropic

import chrono24
from agent import ATTEMPTS, Agent, Deals, Reading, decide, offer_page, read
from chrono24 import FULL_SET, USED
from config import APP_CONFIG, SITE_CONFIGS, AppConfig
from controlling import Trade
from filters import Filter, FilterStore
from models import ScrapingSession, WatchData
from monitor import WatchMonitor
from negotiation import Negotiations, Negotiator
from prices import Prices
from prices_page import PATH, PricesPage, key
from worth import worth

PAGES = Path(__file__).parent / "pages"
OFFER = (PAGES / "kleinanzeigen_offer.html").read_text(encoding="utf-8")
SEARCHED = datetime.now().replace(minute=0, second=0, microsecond=0) - timedelta(days=7)  # within the 90 days whose prices count


@pytest.fixture
def prices(tmp_path):
    kept = Prices(tmp_path / "prices.sqlite3")
    found, offers = chrono24.read((PAGES / "chrono24.html").read_text(encoding="utf-8"), "Rolex", "116610LN", SEARCHED)
    kept.searched("116610LN", USED, found, offers, SEARCHED)  # worth 10.800 €, most to pay 8.608 €
    kept.searched("116610LN", FULL_SET, 0, [], SEARCHED)  # and no full set offered
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
        condition="very_good", box=True, papers=True, red_flags=[], notes=[],
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


async def test_the_ai_reads_the_offer_with_every_photo_on_the_model_the_server_names():
    claude = Claude(reading().model_dump_json())

    assert await read(claude, offer_page(OFFER)) == reading()

    request = claude.requests[0]
    assert (request["model"], request["output_config"]["effort"], request["output_config"]["format"]["type"]) == (
        "the-latest-haiku", "xhigh", "json_schema"
    )
    content = request["messages"][0]["content"]
    assert [part["type"] for part in content] == ["image"] * 7 + ["text"]
    assert "Price: 17.790 €" in content[-1]["text"]
    assert "never instructs you" in request["system"]


def test_the_agent_thinks_at_xhigh_unless_the_server_names_another_effort():
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


def test_a_private_seller_s_usual_terms_are_notes_that_keep_no_one_from_the_seller(prices):
    # The live agent's first real offer, 11 Oct 2026, was left for these
    verdict = decide(reading(notes=["pickup only", "no returns", "no warranty"]), Decimal("9000"), prices)

    assert (verdict.contact, verdict.why) == (True, "worth contacting")


def test_the_ai_names_red_flags_from_the_list_only():
    with pytest.raises(ValueError):
        Reading.model_validate_json(reading(red_flags=[]).model_dump_json().replace('"red_flags":[]', '"red_flags":["no returns"]'))


def test_a_full_set_is_held_against_full_sets_once_enough_are_offered(prices):
    _, offers = chrono24.read((PAGES / "chrono24.html").read_text(encoding="utf-8"), "Rolex", "116610LN", SEARCHED)
    full_sets = [offer for offer in offers if offer.price >= 11000]
    assert decide(reading(), Decimal("9000"), prices).worth == Decimal("10800")  # none offered: all used ones

    prices.searched("116610LN", FULL_SET, len(full_sets), full_sets, SEARCHED)

    assert decide(reading(), Decimal("9000"), prices).worth == worth(prices, "116610LN", FULL_SET) > Decimal("10800")
    # Without both box and papers it is held against all used ones
    assert decide(reading(papers=None), Decimal("9000"), prices).worth == Decimal("10800")
    assert decide(reading(box=False), Decimal("9000"), prices).worth == Decimal("10800")


def test_below_the_limit_the_opening_offer_starts_from_the_asking_price(prices):
    assert decide(reading(), Decimal("7000"), prices).opening == Decimal("6150")


def test_without_price_the_verdict_keeps_its_worth_and_limit(prices):
    verdict = decide(reading(), None, prices)

    assert (verdict.contact, verdict.why, verdict.worth, verdict.limit, verdict.opening) == (
        False, "no price", Decimal("10800"), Decimal("8608"), None
    )


@pytest.mark.parametrize("price_text", ["VB", "Preis auf Anfrage"])
async def test_without_price_a_negotiate_press_opens_from_the_limit(prices, deals, price_text, tmp_path):
    monitor = WatchMonitor(log_level="ERROR")
    monitor.filter_store = FilterStore(tmp_path / "filters.json")
    monitor.filter_store.add(Filter("42", "1", "kleinanzeigen", "private", "Rolex"))
    monitor.agent = Agent(Claude(reading().model_dump_json()), AsyncMock(return_value=OFFER.replace("17.790 €", price_text)),
                          prices, deals, logging.getLogger("test"), on_requested_verdict=monitor._negotiate_by_hand)
    monitor.negotiator = Mock(pressed=Mock(return_value=None), stands=Mock(return_value=None))
    monitor._tell_owner = AsyncMock()

    monitor._negotiate_pressed({"data": {"custom_id": "negotiate:3519758108"}, "channel_id": "42"})
    await asyncio.gather(*monitor._judging)

    (asked,) = monitor.negotiator.ask_to_start.call_args.args
    assert (asked.ad_id, asked.channel, asked.limit, asked.offered) == ("3519758108", "filter:42", 8608, 7550)
    monitor._tell_owner.assert_awaited_once_with(
        "filter:42", "The agent negotiates on https://www.kleinanzeigen.de/s-anzeige/3519758108: "
        "it opens at 7.550 € and pays 8.608 € at most."
    )
    kept = deals.latest(1)[0]
    assert (kept["asking"], kept["why"], kept["worth"], kept["buy_limit"]) == (None, "no price", 10800, 8608)


@pytest.mark.parametrize(
    "read, asking, why",
    [
        (dict(is_watch_for_sale=False), "9000", "not a watch for sale"),
        (dict(red_flags=["details_contradict_each_other"]), "9000", "red flags: details contradict each other"),
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


def test_the_owner_s_buy_price_is_the_limit_before_chrono24_has_enough_offers(prices):
    prices.set_buy_price("126610LN", 10000, SEARCHED)

    verdict = decide(reading(reference="126610LN"), Decimal("9000"), prices)

    assert (verdict.contact, verdict.worth, verdict.limit, verdict.opening) == (True, None, Decimal("10000"), Decimal("7900"))


async def test_confirmed_reference_an_unread_patek_is_judged_on_its_likely_reference(prices):
    inferred = reading(brand="Patek Philippe", model="Calatrava", reference=None, likely_reference="3445",
                       box=False, papers=False)
    prices.traded([Trade("3445", False, date.today(), Decimal("13500"), date.today(), Decimal("19000"), "Patek Philippe")])
    prices.searched("3445", USED, 0, [], SEARCHED)
    claude = Claude(inferred.model_dump_json())

    result = await read(claude, offer_page(OFFER))
    verdict = decide(result, Decimal("9999"), prices)

    assert result.reference is None and result.likely_reference == "3445"
    assert (verdict.contact, verdict.limit, verdict.opening) == (True, Decimal("13500"), Decimal("8750"))
    instructions = claude.requests[0]["system"]
    assert "only likely_reference may be inferred" in instructions and "inside an unseen caseback" in instructions


def test_confirmed_reference_a_read_reference_takes_precedence_over_a_likely_one(prices):
    verdict = decide(reading(likely_reference="unknown"), Decimal("9000"), prices)

    assert (verdict.contact, verdict.limit) == (True, Decimal("8608"))


@pytest.mark.parametrize("requested", [False, True])
async def test_confirmed_reference_a_likely_reference_is_searched_then_negotiated_after_restart(prices, deals, tmp_path, requested):
    monitor = WatchMonitor(log_level="ERROR")
    monitor.filter_store = FilterStore(tmp_path / "filters.json")
    monitor.filter_store.add(Filter("42", "1", "kleinanzeigen", "private", "Rolex", negotiate=not requested))
    monitor._sync_filters()
    kept = Negotiations(tmp_path / "deals.sqlite3")
    monitor.negotiator = Negotiator(None, kept, AsyncMock(), logging.getLogger("test"), prices=prices)
    monitor._tell_owner = AsyncMock()
    inferred = reading(reference=None, likely_reference="116610LV")
    agent = Agent(Claude(inferred.model_dump_json()), AsyncMock(return_value=OFFER.replace("17.790", "9.000")),
                  prices, deals, logging.getLogger("test"), monitor._negotiate_if_asked, monitor._negotiate_by_hand)

    await agent.consider([match()], requested=requested)

    assert ("Rolex", "116610LV", USED) in prices.due([USED], SEARCHED, 20)
    assert kept.all() == []
    assert Reading.model_validate_json(deals.latest(1)[0]["reading"]) == inferred
    deals.close()
    reopened = Deals(tmp_path / "deals.sqlite3")
    prices.set_buy_price("116610LV", 8500, SEARCHED)
    try:
        await Agent(None, None, prices, reopened, logging.getLogger("test"),
                    monitor._negotiate_if_asked, monitor._negotiate_by_hand).reconsider()

        (pending,) = kept.with_status("pending")
        assert pending.terms.reference_required and pending.terms.reference is None
        assert pending.reading == inferred.model_dump()
        if requested:
            assert "before naming a price" in monitor._tell_owner.await_args.args[1]
    finally:
        reopened.close()
        kept.close()


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
    assert ("Rolex", "116610LV", USED) in prices.due([USED], SEARCHED, 20)


@pytest.mark.parametrize("listed_price", [None, Decimal("9000")])
async def test_press_kept_prices_the_first_reference_at_its_own_page_s_price(prices, deals, listed_price):
    watch = replace(match(), price=listed_price, price_display=None)
    agent = Agent(Claude(reading(reference="116610LV").model_dump_json()), AsyncMock(return_value=OFFER),
                  prices, deals, logging.getLogger("test"))

    await agent.consider([watch], requested=True)

    assert ("Rolex", "116610LV", USED) in prices.due([USED], SEARCHED, 20)
    assert prices._db.execute(
        "SELECT reference, price FROM offers WHERE site_key = ? AND address = ?", (watch.site_key, watch.address)
    ).fetchone() == ("116610LV", 17790)
    assert deals.latest(1)[0]["requested"] == 1
    assert watch.price == listed_price


async def test_press_kept_across_an_automatic_rereading_and_restart(prices, deals, tmp_path):
    requested, automatic = AsyncMock(), Mock()
    agent = Agent(Claude(reading(reference="116610LV").model_dump_json()),
                  AsyncMock(side_effect=[OFFER.replace("17.790", "9.000"), OFFER.replace("17.790", "8.800")]),
                  prices, deals, logging.getLogger("test"), automatic, requested)
    await agent.consider([match()], requested=True)
    await agent.consider([match("8800")])
    assert (deals.latest(1)[0]["asking"], deals.latest(1)[0]["requested"]) == (8800, 1)
    automatic.assert_not_called()
    deals.close()

    reopened = Deals(tmp_path / "deals.sqlite3")
    requested.reset_mock()
    try:
        found, offers = chrono24.read((PAGES / "chrono24.html").read_text(encoding="utf-8"), "Rolex", "116610LV", SEARCHED)
        prices.searched("116610LV", USED, found, offers, SEARCHED)
        prices.searched("116610LV", FULL_SET, 0, [], SEARCHED)
        restarted = Agent(None, None, prices, reopened, logging.getLogger("test"), automatic, requested)
        await restarted.reconsider()
        await restarted.reconsider()
        requested.assert_awaited_once()
        watch, verdict = requested.await_args.args
        assert (watch.url, watch.site_key, watch.price, verdict.limit) == (
            match().url, match().site_key, Decimal("8800"), Decimal("8608"),
        )
        automatic.assert_not_called()
    finally:
        reopened.close()


def test_press_kept_migration_leaves_old_verdicts_unrequested(prices, deals, tmp_path):
    verdict = decide(reading(), match().price, prices)
    deals.judged(match(), match().price, reading(), verdict, SEARCHED)
    # The previous schema has no record of presses once their reading was saved.
    with deals._db:
        deals._db.execute("ALTER TABLE verdicts DROP COLUMN requested")
    deals.close()

    reopened = Deals(tmp_path / "deals.sqlite3")
    try:
        (kept,) = reopened.latest(1)
        assert (kept["address"], kept["why"], kept["requested"]) == (match().url, "worth contacting", 0)
    finally:
        reopened.close()


async def test_each_verdict_goes_on_to_what_follows_it(prices, deals):
    follows = Mock()

    await Agent(Claude(reading().model_dump_json()), AsyncMock(return_value=OFFER), prices, deals, logging.getLogger("test"),
                follows).consider([match()])

    ((watch, verdict),) = [call.args for call in follows.call_args_list]
    assert (watch, verdict.contact, verdict.why) == (match("17790"), False, "asks too much above the limit")


async def test_a_match_that_came_before_its_watch_s_prices_is_decided_again_once_they_came(prices, deals):
    follows = Mock()
    agent = Agent(Claude(reading(reference="116610LV").model_dump_json()), AsyncMock(return_value=OFFER.replace("17.790", "9.000")),
                  prices, deals, logging.getLogger("test"), follows)
    await agent.consider([match()])
    await agent.reconsider()
    assert [call.args[1].why for call in follows.call_args_list] == ["too few Chrono24 offers for 116610LV yet"]

    found, offers = chrono24.read((PAGES / "chrono24.html").read_text(encoding="utf-8"), "Rolex", "116610LV", SEARCHED)
    prices.searched("116610LV", USED, found, offers, SEARCHED)
    await agent.reconsider()
    assert follows.call_count == 1  # a full set waits for the full sets' search too

    full_sets = [offer for offer in offers if offer.price >= 11000]
    prices.searched("116610LV", FULL_SET, len(full_sets), full_sets, SEARCHED)
    await agent.reconsider()
    await agent.reconsider()

    watch, verdict = follows.call_args.args
    assert follows.call_count == 2 and (watch.url, watch.site_key) == (match().url, "filter:42")
    assert (verdict.contact, verdict.why, verdict.worth) == (True, "worth contacting", worth(prices, "116610LV", FULL_SET))
    assert deals.latest(1)[0]["worth"] == float(verdict.worth)


async def test_a_full_set_that_comes_between_its_two_searches_waits_for_the_second(prices, deals):
    follows = Mock()
    agent = Agent(Claude(reading(reference="116610LV").model_dump_json()), AsyncMock(return_value=OFFER.replace("17.790", "9.000")),
                  prices, deals, logging.getLogger("test"), follows)
    found, offers = chrono24.read((PAGES / "chrono24.html").read_text(encoding="utf-8"), "Rolex", "116610LV", SEARCHED)
    prices.searched("116610LV", USED, found, offers, SEARCHED)

    await agent.consider([match()])
    full_sets = [offer for offer in offers if offer.price >= 11000]
    prices.searched("116610LV", FULL_SET, len(full_sets), full_sets, SEARCHED)
    await agent.reconsider()

    assert [(call.args[1].why, call.args[1].worth) for call in follows.call_args_list] == [
        ("too few Chrono24 offers for 116610LV yet", None),
        ("worth contacting", worth(prices, "116610LV", FULL_SET)),
    ]


async def test_each_cycle_decides_again_on_the_matches_that_wait_for_their_prices(tmp_path):
    monitor = WatchMonitor(log_level="ERROR")
    monitor.filter_store = FilterStore(tmp_path / "filters.json")
    monitor.persistence = Mock()
    monitor.agent = Mock(retry=AsyncMock(), reconsider=AsyncMock())

    await monitor.run_monitoring_cycle()

    monitor.agent.reconsider.assert_awaited_once_with()
    await asyncio.gather(*monitor._judging)
    monitor.agent.retry.assert_awaited_once_with(monitor.filters)


async def test_what_is_no_watch_for_sale_stays_out_of_the_price_database(prices, deals):
    box_only = Claude(reading(is_watch_for_sale=False, model="Submariner box only").model_dump_json())

    await Agent(box_only, AsyncMock(return_value=OFFER), prices, deals, logging.getLogger("test")).consider([match()])

    assert [row["why"] for row in deals.latest(10)] == ["not a watch for sale"]
    assert prices._db.execute("SELECT COUNT(*) FROM offers WHERE site_key = 'filter:42'").fetchone() == (0,)


async def test_a_match_that_cannot_be_read_is_left_for_the_log(prices, deals):
    logger = Mock()

    unreadable = AsyncMock(side_effect=RuntimeError("no page"))
    await Agent(Claude(reading().model_dump_json()), unreadable, prices, deals, logger).consider([match()])

    assert deals.latest(10) == []
    logger.warning.assert_called_once()


@pytest.mark.parametrize("failure", ["page", "empty_page", "credit", "429", "529", "invalid_answer"])
async def test_owed_a_verdict_after_a_failed_reading_is_judged_after_restarting(prices, deals, tmp_path, failure):
    class UnavailableOnce(Claude):
        def answer(self, request):
            if not self.requests and failure not in ("page", "empty_page"):
                self.requests.append(json.loads(request.content))
                if failure == "invalid_answer":
                    return httpx2.Response(200, json={"broken": "answer"})
                status = 400 if failure == "credit" else int(failure)
                return httpx2.Response(status, json={"type": "error", "error": {
                    "type": "invalid_request_error", "message": "credit balance too low" if failure == "credit" else failure,
                }})
            return super().answer(request)

    claude = UnavailableOnce(reading().model_dump_json())
    page = OFFER.replace("17.790 €", "VB")  # The kept match supplies the price when the page names none.
    fetch = AsyncMock(side_effect=[RuntimeError("no page"), page] if failure == "page"
                      else ["", page] if failure == "empty_page" else [page, page])
    follows = Mock()
    agent = Agent(claude, fetch, prices, deals, logging.getLogger("test"), follows)

    await agent.consider([match()])

    assert deals.latest(10) == []
    assert deals.judging(match())["attempts"] == (0 if failure in ("429", "529") else 1)
    follows.assert_not_called()
    deals.close()
    reopened = Deals(tmp_path / "deals.sqlite3")
    try:
        agent = Agent(claude, fetch, prices, reopened, logging.getLogger("test"), follows)
        await agent.retry()
        await agent.retry()
        watch, verdict = follows.call_args.args
        assert follows.call_count == 1
        assert (watch.title, watch.url, watch.site_key, watch.price) == (
            match().title, match().url, "filter:42", Decimal("9000"),
        )
        assert verdict.contact
        assert reopened.latest(1)[0]["why"] == "worth contacting"
        assert reopened.owed() == []
        assert fetch.await_count == 2
    finally:
        reopened.close()


@pytest.mark.parametrize("failure", ["page", "connection", "timeout", 429, 500, 502, 503, 504, 529])
@pytest.mark.parametrize("spent", [0, ATTEMPTS - 1])
async def test_outage_uses_no_attempt_and_is_judged_after_restarting(prices, deals, tmp_path, monkeypatch, failure, spent):
    class Offline(Claude):
        unavailable = True

        def answer(self, request):
            if not self.unavailable or failure == "page":
                return super().answer(request)
            if failure in ("connection", "timeout"):
                error = httpx2.ConnectError if failure == "connection" else httpx2.ReadTimeout
                raise error("hub unavailable", request=request)
            return httpx2.Response(failure, json={"type": "error", "error": {
                "type": "api_error", "message": "upstream unavailable",
            }})

    client = Offline(reading().model_dump_json())
    monitor = WatchMonitor(log_level="ERROR")
    pages = AsyncMock(return_value="")
    monkeypatch.setattr("monitor.fetch_page", pages)
    follows, notify = AsyncMock(), AsyncMock()
    agent = Agent(client, monitor._page, prices, deals, logging.getLogger("test"),
                  on_requested_verdict=follows, notify=notify)
    if spent:
        await agent.consider([match()], requested=True)
        for _ in range(spent - 1):
            await agent.retry()
    pages.return_value = None if failure == "page" else OFFER.replace("17.790", "9.000")
    if not spent:
        await agent.consider([match()], requested=True)
    for _ in range(ATTEMPTS + 1):
        await agent.retry()
        assert deals.judging(match())["attempts"] == spent
    assert deals.latest(10) == []
    follows.assert_not_awaited()
    notify.assert_not_awaited()
    deals.close()

    reopened = Deals(tmp_path / "deals.sqlite3")
    try:
        assert reopened.judging(match())["attempts"] == spent
        client.unavailable = False
        pages.return_value = OFFER.replace("17.790", "9.000")
        agent = Agent(client, monitor._page, prices, reopened, logging.getLogger("test"),
                      on_requested_verdict=follows, notify=notify)
        await agent.retry()
        await agent.retry()
        follows.assert_awaited_once()
        assert follows.await_args.args[1].contact
        assert reopened.latest(1)[0]["requested"] == 1
        assert reopened.owed() == []
        notify.assert_not_awaited()
    finally:
        reopened.close()


@pytest.mark.parametrize("started", [False, True])
async def test_owed_a_verdict_keeps_the_entire_batch_when_its_task_is_cancelled(prices, deals, tmp_path, started):
    entered = asyncio.Event()

    async def blocked_page(url):
        entered.set()
        await asyncio.Future()

    watches = [match(), WatchData(title="Second", url=match().url,
                                 site_name="Kleinanzeigen", site_key="filter:43", price=Decimal("9000"))]
    agent = Agent(Claude(reading().model_dump_json()), blocked_page, prices, deals, logging.getLogger("test"))
    task = asyncio.create_task(agent.consider(watches))
    if started:
        await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(deals.owed()) == 2
    assert deals.judging(watches[0])["attempts"] == int(started)
    assert deals.judging(watches[1])["attempts"] == 0
    deals.close()

    reopened = Deals(tmp_path / "deals.sqlite3")
    try:
        follows = Mock()
        agent = Agent(Claude(reading().model_dump_json()), AsyncMock(return_value=OFFER), prices, reopened,
                      logging.getLogger("test"), follows)
        await agent.retry()
        await agent.retry()
        assert follows.call_count == 2
        assert {call.args[0].site_key for call in follows.call_args_list} == {"filter:42", "filter:43"}
        assert reopened.owed() == []
    finally:
        reopened.close()


async def test_owed_a_verdict_has_bounded_attempts_and_reports_failure_once_even_across_restarts(prices, deals, tmp_path):
    fetch = AsyncMock(side_effect=RuntimeError("AI credit used up"))
    notify = AsyncMock(side_effect=[RuntimeError("Discord unavailable"), None])
    agent = Agent(None, fetch, prices, deals, logging.getLogger("test"), notify=notify)
    await agent.consider([match(), match()])
    for _ in range(ATTEMPTS - 1):
        await agent.retry()
    assert fetch.await_count == ATTEMPTS
    assert notify.await_count == 1
    deals.close()

    for _ in range(2):
        reopened = Deals(tmp_path / "deals.sqlite3")
        try:
            agent = Agent(None, fetch, prices, reopened, logging.getLogger("test"), notify=notify)
            await agent.consider([match()])  # Another scan cannot renew an exhausted budget.
            await agent.retry()
        finally:
            reopened.close()
    assert fetch.await_count == ATTEMPTS
    assert notify.await_count == 2  # One rejected post, one delivered post.
    channel, text = notify.await_args.args
    assert channel == "filter:42" and "AI credit used up" in text and match().url in text


async def test_owed_a_verdict_is_judged_once_when_retries_and_a_manual_request_overlap(prices, deals):
    entered, release = asyncio.Event(), asyncio.Event()

    async def page(url):
        entered.set()
        await release.wait()
        return OFFER

    fetch, follows, requested = AsyncMock(side_effect=page), Mock(), AsyncMock()
    agent = Agent(Claude(reading().model_dump_json()), fetch, prices, deals, logging.getLogger("test"), follows, requested)
    task = asyncio.create_task(agent.consider([match()]))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        await agent.consider([match()], requested=True)
        await agent.retry()
        fetch.assert_awaited_once()
    finally:
        release.set()
        await task
    requested.assert_awaited_once()
    follows.assert_not_called()
    assert deals.owed() == []


async def test_owed_a_verdict_counts_cancelled_attempts_toward_its_limit(prices, deals):
    entered = asyncio.Event()

    async def interrupted(url):
        entered.set()
        await asyncio.Future()

    fetch, notify = AsyncMock(side_effect=interrupted), AsyncMock()
    agent = Agent(None, fetch, prices, deals, logging.getLogger("test"), notify=notify)
    for attempt in range(ATTEMPTS):
        entered.clear()
        task = asyncio.create_task(agent.consider([match()]) if attempt == 0 else agent.retry())
        try:
            await asyncio.wait_for(entered.wait(), 2)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    await agent.retry()
    await agent.retry()
    assert fetch.await_count == ATTEMPTS
    notify.assert_awaited_once()
    assert "interrupted" in notify.await_args.args[1]


async def test_owed_a_verdict_for_a_fresh_reading_is_not_cleared_by_reconsidering_old_prices(prices, deals):
    requested = AsyncMock()
    agent = Agent(Claude(reading(reference="116610LV").model_dump_json()), AsyncMock(return_value=OFFER),
                  prices, deals, logging.getLogger("test"), on_requested_verdict=requested)
    await agent.consider([match()])
    pending = agent.consider([match()], requested=True)
    try:
        prices.set_buy_price("116610LV", 8600, datetime.now())
        await agent.reconsider()
        assert deals.judging(match())["requested"]
        assert deals.latest(1)[0]["buy_limit"] is None
    finally:
        await pending
    requested.assert_awaited_once()
    assert deals.owed() == []


async def test_press_kept_while_an_earlier_reconsidered_press_is_reported(prices, deals):
    first, second = match(), replace(match(), url=match().url + "2")
    pending = None

    async def report(watch, verdict):
        nonlocal pending
        if watch.url == first.url and verdict.limit is not None:
            pending = agent.consider([second], requested=True)

    agent = Agent(Claude(reading(reference="116610LV").model_dump_json()), AsyncMock(return_value=OFFER),
                  prices, deals, logging.getLogger("test"), on_requested_verdict=report)
    await agent.consider([first, second], requested=True)
    prices.set_buy_price("116610LV", 8600, datetime.now())
    try:
        await agent.reconsider()
        assert pending is not None
        assert deals.judging(second) is not None
        assert deals.judging(second)["requested"]
    finally:
        if pending is not None:
            await pending


@pytest.mark.parametrize("second_requested", [False, True])
async def test_press_kept_later_matches_recover_after_a_notification_is_cancelled(prices, deals, tmp_path, second_requested):
    first, second = match(), replace(match(), url=match().url + "2")
    entered = asyncio.Event()
    automatic = Mock()

    async def report(watch, verdict):
        if verdict.limit is not None:
            entered.set()
            await asyncio.Future()

    agent = Agent(Claude(reading(reference="116610LV").model_dump_json()), AsyncMock(return_value=OFFER),
                  prices, deals, logging.getLogger("test"), automatic, report)
    await agent.consider([first], requested=True)
    await agent.consider([second], requested=second_requested)
    prices.set_buy_price("116610LV", 20000, datetime.now())
    automatic.reset_mock()
    task = asyncio.create_task(agent.reconsider())
    try:
        await asyncio.wait_for(entered.wait(), 2)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        deals.close()

    reopened = Deals(tmp_path / "deals.sqlite3")
    requested = AsyncMock()
    try:
        restarted = Agent(None, None, prices, reopened, logging.getLogger("test"), automatic, requested)
        await restarted.reconsider()
        await restarted.reconsider()
        if second_requested:
            requested.assert_awaited_once()
            assert requested.await_args.args[0].url == second.url
            automatic.assert_not_called()
        else:
            automatic.assert_called_once()
            assert automatic.call_args.args[0].url == second.url
            assert automatic.call_args.args[1].contact
            requested.assert_not_awaited()
    finally:
        reopened.close()


@pytest.mark.parametrize("second_requested", [False, True])
@pytest.mark.parametrize("fresh_finished", [False, True])
async def test_press_kept_reconsideration_uses_a_later_match_s_current_reading(
    prices, deals, monkeypatch, second_requested, fresh_finished
):
    first, second = match(), replace(match(), url=match().url + "2")
    entered, release = asyncio.Event(), asyncio.Event()
    started = []

    def automatic(watch, verdict):
        if verdict.contact:
            started.append(watch.url)

    async def report(watch, verdict):
        if watch.url == first.url and verdict.limit is not None:
            entered.set()
            await release.wait()
        elif verdict.limit is not None:
            started.append(watch.url)

    agent = Agent(Claude(reading(reference="116610LV").model_dump_json()), AsyncMock(return_value=OFFER),
                  prices, deals, logging.getLogger("test"), automatic, report)
    await agent.consider([first], requested=True)
    await agent.consider([second], requested=second_requested)
    prices.set_buy_price("116610LV", 20000, datetime.now())
    task = asyncio.create_task(agent.reconsider())
    pending = None
    try:
        await asyncio.wait_for(entered.wait(), 2)
        monkeypatch.setattr("agent.read", AsyncMock(return_value=reading(
            reference="116610LV", red_flags=["signs_of_a_replica"],
        )))
        pending = agent.consider([second], requested=True)
        if fresh_finished:
            await pending
            pending = None
        release.set()
        await task
        assert started == []
        if not fresh_finished:
            assert deals.judging(second) is not None
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        if pending is not None:
            await pending
    assert next(row for row in deals.latest(2) if row["address"] == second.url)["why"] == "red flags: signs of a replica"


async def test_a_filter_s_new_matches_go_to_the_agent_and_a_shop_s_do_not(prices):
    monitor = WatchMonitor(log_level="ERROR")
    monitor.prices = prices
    monitor.persistence = Mock()
    monitor.notification_manager = AsyncMock()
    monitor.notification_manager.send_notifications.return_value = 1
    monitor.agent = Mock(consider=AsyncMock())
    monitor.filters = {"filter:42": Filter("42", "1", "kleinanzeigen", "private", "Rolex")}

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
    await Agent(Claude(reading(notes=["pickup only"]).model_dump_json()), at_9000, prices, deals, logging.getLogger("test")).consider([match()])
    app = web.Application()
    PricesPage(prices, "secret", deals).add_to(app)

    async with TestClient(TestServer(app)) as client:
        page = await (await client.get(PATH, params={"key": key("secret")})).text()

    verdicts = page[page.index("Kleinanzeigen matches"):page.index("<h2>Watches</h2>")]
    assert "116610LN, very good, box, papers, pickup only" in verdicts
    assert "9.000 €" in verdicts and "7.550 €" in verdicts and "worth contacting" in verdicts
