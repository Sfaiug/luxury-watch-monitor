"""The buying agent's negotiation: what it answers a seller by the owner's terms, and how it writes to them."""

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx2
import pytest
from anthropic import AsyncAnthropic

import negotiation
from agent import Verdict
from filters import Filter, FilterStore
from kleinanzeigen_messages import Unsent
from models import WatchData
from monitor import WatchMonitor
from negotiation import Move, Negotiation, Negotiations, Negotiator, SellerSays, Terms, filled, move

LIMIT, OPENING = 8600, 7550


def says(**said):
    stated = dict(price=None, accepts_offer=False, bank_transfer=None, delivery=None, contract=None, id_card=None,
                  ended=False, red_flags=[], question=None)
    stated.update(said)
    return SellerSays(**stated)


def test_an_offer_the_seller_accepts_is_the_price_and_the_rest_is_settled_next():
    terms = Terms()

    answer = move(LIMIT, OPENING, terms, says(accepts_offer=True), pictures=False)

    assert (answer.kind, answer.price, terms.price) == ("agreed", 7550, 7550)
    assert list(terms.open()) == ["payment by bank transfer", "insured shipping, or else pickup",
                                  "the purchase contract the buyer sends to sign", "a picture of the seller's ID card"]


def test_a_seller_asking_a_little_more_is_met_at_their_price():
    answer = move(LIMIT, OPENING, Terms(), says(price=7700), False)
    assert (answer.kind, answer.price) == ("agreed", 7700)
    assert move(LIMIT, OPENING, Terms(), says(price=7000), False).price == 7000  # below the offer: theirs


def test_the_agent_gives_half_the_room_to_its_limit_and_no_more_than_halfway_to_the_seller():
    assert move(LIMIT, OPENING, Terms(), says(price=8500), False) == Move("offer", 8000, "the seller asks 8.500 €")

    # A seller who holds out far above the limit: 8.000, 8.300, 8.450, 8.500, then the limit as the last offer
    offers, offered = [], 8000
    while offered < LIMIT:
        answer = move(LIMIT, offered, Terms(), says(price=11000), False)
        offers.append((answer.kind, answer.price))
        offered = answer.price
    assert offers == [("offer", 8300), ("offer", 8450), ("offer", 8500), ("final", LIMIT)]

    assert move(LIMIT, LIMIT, Terms(), says(price=9500), False).kind == "farewell"
    assert move(2600, 2500, Terms(), says(price=2580), False).price == 2580  # never more than the seller asks


def test_a_seller_who_has_not_come_down_since_its_last_offer_is_met_with_that_offer_once_then_the_next_step():
    terms, answers, offered = Terms(), [], OPENING
    for asked in (8500, 8500, 8500, 8450):
        answer = move(LIMIT, offered, terms, says(price=asked), False)
        answers.append((answer.kind, answer.price))
        offered = answer.price or offered

    assert answers == [("offer", 8000), ("hold", None), ("offer", 8250), ("offer", 8350)]  # the last: they came down


def test_a_seller_repeating_the_asking_price_after_the_opening_offer_is_met_with_it_once():
    terms = Terms()
    assert move(LIMIT, OPENING, terms, says(price=9900), False, opening=True).kind == "offer"

    assert move(LIMIT, OPENING, terms, says(price=9900), False).kind == "hold"


def test_a_seller_turning_the_offer_down_with_no_price_is_asked_theirs_not_offered_the_same():
    terms = Terms()
    move(LIMIT, OPENING, terms, says(), False, opening=True)

    assert move(LIMIT, OPENING, terms, says(), False) == Move("ask", None, "the seller names no price")


def test_a_seller_naming_no_price_now_stands_at_the_one_named_before():
    terms = Terms()
    assert move(LIMIT, OPENING, terms, says(price=8500), False) == Move("offer", 8000, "the seller asks 8.500 €")

    assert move(LIMIT, 8000, terms, says(), False).kind == "hold"
    assert move(LIMIT, 8000, terms, says(), False) == Move("offer", 8250, "the seller asks 8.500 €")

    assert move(LIMIT, 8250, terms, says(price=12000), False).kind == "hold"
    assert move(LIMIT, 8250, terms, says(), False) == Move("offer", 8400, "the seller asks 12.000 €")  # their latest


def test_the_agent_offers_whole_steps_its_last_below_a_limit_that_is_none():
    assert move(8366, 8250, Terms(), says(price=9000), False) == Move("final", 8350, "the seller asks 9.000 €")
    assert move(8366, 8350, Terms(), says(price=8400), False).kind == "farewell"
    assert move(8366, 8350, Terms(), says(price=8366), False) == Move("agreed", 8366, "next: payment by bank transfer")
    assert move(2633, 2500, Terms(), says(price=2599), False) == Move("agreed", 2599, "next: payment by bank transfer")


def test_a_seller_holding_out_to_the_agent_s_last_offer_then_agreeing_term_by_term_is_not_handed_over():
    terms, offered, written = Terms(), OPENING, ["first", "offer"]
    terms.asked = 11000
    while (answer := move(LIMIT, offered, terms, says(price=11000), False)).kind != "final":
        written.append(answer.kind)
        offered = answer.price or offered
    written.append("final")
    move(LIMIT, LIMIT, terms, says(accepts_offer=True), False)
    for agreed in (dict(bank_transfer=True), dict(delivery="shipping"), dict(contract=True), dict(id_card=True)):
        written.append(move(LIMIT, LIMIT, terms, says(**agreed), True).kind)

    assert written[-1] == "done" and written.count("hold") == 5
    assert len(written) <= negotiation.MOST_WRITTEN


@pytest.mark.parametrize("agreed, refusing", [
    (dict(), dict(bank_transfer=False)),
    (dict(bank_transfer=True, delivery="shipping"), dict(contract=False)),
    (dict(bank_transfer=True, delivery="shipping", contract=True), dict(id_card=False)),
])
def test_a_seller_refusing_the_term_asked_for_is_asked_once_more_then_bid_farewell(agreed, refusing):
    terms = Terms(**agreed)

    first = move(LIMIT, OPENING, terms, says(price=7600, **refusing), False)
    assert (first.kind, first.price, len(first.refused)) == ("agreed", 7600, 1)  # the price talk goes on beside it

    assert move(LIMIT, OPENING, terms, says(**refusing), False).kind == "farewell"


def test_a_term_refused_before_its_turn_waits_for_it():
    terms = Terms()

    assert move(LIMIT, OPENING, terms, says(accepts_offer=True, id_card=False), False) == Move(
        "agreed", OPENING, "next: payment by bank transfer")
    assert move(LIMIT, OPENING, terms, says(bank_transfer=True, id_card=False), False) == Move(
        "settle", None, "next: insured shipping, or else pickup")
    assert move(LIMIT, OPENING, terms, says(delivery="shipping", contract=True, id_card=False), False) == Move(
        "settle", None, "next: a picture of the seller's ID card", ["a picture of the ID card"])


def test_a_term_the_seller_agreed_and_then_refuses_is_open_again():
    terms = Terms(price=OPENING, bank_transfer=True, delivery="shipping", contract=True, id_card=True)

    assert move(LIMIT, OPENING, terms, says(bank_transfer=False), False) == Move(
        "settle", None, "next: payment by bank transfer", ["bank transfer"])
    assert list(terms.open()) == ["payment by bank transfer"]


def test_the_seller_is_asked_for_one_term_at_a_time_in_turn():
    terms, asked = Terms(price=OPENING), []
    for agreed in (dict(bank_transfer=True), dict(delivery="shipping"), dict(contract=True)):
        answer = move(LIMIT, OPENING, terms, says(), False)
        asked.append((answer.kind, answer.price, answer.why))
        move(LIMIT, OPENING, terms, says(**agreed), False)

    assert asked == [("settle", None, "next: payment by bank transfer"), ("settle", None, "next: insured shipping, or else pickup"),
                     ("settle", None, "next: the purchase contract the buyer sends to sign")]
    assert move(LIMIT, OPENING, terms, says(), False).why == "next: a picture of the seller's ID card"


def test_before_its_first_offer_the_agent_opens_with_it_whatever_the_seller_asks():
    assert move(LIMIT, OPENING, Terms(), says(price=9500), False, opening=True) == Move("offer", OPENING, "its opening offer")
    assert move(LIMIT, OPENING, Terms(), says(price=7700), False, opening=True) == Move("offer", OPENING, "its opening offer")
    assert move(LIMIT, OPENING, Terms(), says(), False, opening=True) == Move("offer", OPENING, "its opening offer")
    assert move(LIMIT, OPENING, Terms(), says(accepts_offer=True), False, opening=True).kind == "offer"  # nothing to accept
    assert move(LIMIT, OPENING, Terms(), says(price=7000), False, opening=True) == Move("agreed", 7000, "next: payment by bank transfer")


def test_a_seller_asking_more_than_the_agreed_price_opens_the_price_again_from_it():
    terms = Terms(price=OPENING, bank_transfer=True, delivery="shipping", contract=True, id_card=True)

    assert move(LIMIT, OPENING, terms, says(price=OPENING), False).kind == "done"  # the agreed price named again
    assert move(LIMIT, 7000, terms, says(price=8000), False) == Move("offer", 7750, "the seller asks 8.000 €")
    assert terms.price is None


def test_a_red_flag_or_a_sold_watch_ends_it_without_a_word():
    assert move(LIMIT, OPENING, Terms(), says(red_flags=["payment_or_contact_outside_kleinanzeigen"]), False).kind == "end"
    assert move(LIMIT, OPENING, Terms(), says(ended=True), False).kind == "end"


def test_all_is_agreed_once_the_id_card_is_shown_not_only_promised():
    terms = Terms(price=OPENING, bank_transfer=True, delivery="shipping", contract=True)

    assert move(LIMIT, OPENING, terms, says(id_card=True), pictures=False).kind == "settle"
    assert move(LIMIT, OPENING, terms, says(id_card=True), pictures=True) == Move("done", OPENING, "all agreed")


TITLE = "Rolex Submariner Date 126610LN"


@pytest.mark.parametrize("written, sent", [
    ("Ist die Uhr noch da? Ich biete [BETRAG].", "Ist die Uhr noch da? Ich biete 8.000 €."),
    ("Ist die Submariner 126610LN noch da? Abholung ginge um 14 Uhr, [BETRAG]?", "Ist die Submariner 126610LN noch da? "
     "Abholung ginge um 14 Uhr, 8.000 €?"),  # the watch's own number, and one under 100
    ("Ich würde [BETRAG] € zahlen, oder € [BETRAG]?", None),  # twice
    ("Ich würde [BETRAG] € zahlen.", "Ich würde 8.000 € zahlen."),  # its sign is the amount's
    ("Abholung ginge um 14.30 Uhr, [BETRAG]? Sie hat 40,5 mm.", "Abholung ginge um 14.30 Uhr, 8.000 €? Sie hat 40,5 mm."),
    ("Ich biete [BETRAG], notfalls 8.000,50.", None),
    ("Ich biete [BETRAG] oder 8,5k", None),
    ("Ich lege fünfhundert drauf: [BETRAG]", None),
    ("[BETRAG], oder achteinhalb?", None),
    ("[BETRAG] Euro, das sind viele Euro", None),
    ("[BETRAG], Baujahr 2019?", None),
    ("Ich biete [BETRAG], notfalls auch 8 000.", None),  # thousands apart by a space
    ("Ich biete [BETRAG], notfalls auch 8\u202f000.", None),
    ("Ich biete [BETRAG], notfalls auch 8'000.", None),
    ("Ich biete [BETRAG], notfalls auch 8 000,00.", None),
    ("Ich biete [BETRAG], notfalls auch 8'000.00.", None),
    ("Einverstanden!", None),  # the amount nowhere
    ("[BETRAG] oder [BETRAG]", None),
])
def test_the_code_writes_the_amount_in_and_the_ai_s_own_words_name_no_sum(written, sent):
    assert filled(written, 8000, TITLE) == sent


def test_a_message_with_no_amount_decided_has_none():
    assert filled("Schade, dann passt es leider nicht.", None, TITLE) == "Schade, dann passt es leider nicht."
    assert filled("Schade, [BETRAG] ist zu wenig.", None, TITLE) is None


@dataclass
class Said:
    outbound: bool
    text: str
    attachments: int = 0


class Box:
    """The owner's message box, with one seller in it."""

    def __init__(self, contact_fails=False):
        self.said, self.contact_fails = [], contact_fails

    async def contact(self, ad_id, text):
        if self.contact_fails is True:
            raise RuntimeError("the page did not answer")
        if self.contact_fails:
            raise self.contact_fails
        self.said.append(Said(True, text))
        return "c1"

    async def conversation(self, conversation_id):
        return SimpleNamespace(id=conversation_id, messages=list(self.said))

    async def reply(self, conversation_id, text):
        self.said.append(Said(True, text))

    def seller(self, text, pictures=0):
        self.said.append(Said(False, text, pictures))


class Claude(AsyncAnthropic):
    """The AI: reads the seller from `reads` and writes from `writes`, in turn."""

    def __init__(self, reads=(), writes=()):
        super().__init__(api_key="test", max_retries=0, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(self.answer)))
        self.reads, self.writes, self.asked, self.requests = list(reads), list(writes), [], []

    def answer(self, request):
        self.requests.append(request.content)
        asked = json.loads(request.content)
        writing = "message" in asked["output_config"]["format"]["schema"]["properties"]
        self.asked.append("write" if writing else "read")
        text = json.dumps({"message": self.writes.pop(0)}) if writing else self.reads.pop(0).model_dump_json()
        return httpx2.Response(200, json={"id": "m", "type": "message", "role": "assistant", "model": "m", "stop_reason": "end_turn",
                                          "usage": {"input_tokens": 1, "output_tokens": 1}, "content": [{"type": "text", "text": text}]})


def asked_for():
    return Negotiation(ad_id="3535834511", channel="filter:42", title=TITLE,
                       address="https://www.kleinanzeigen.de/s-anzeige/3535834511", limit=LIMIT, offered=OPENING)


@pytest.fixture
def kept(tmp_path):
    return Negotiations(tmp_path / "deals.sqlite3")


def negotiator(claude, kept, notify=None):
    """The negotiator, answering at once: how long an answer waits is the next test's."""
    return Negotiator(claude, kept, notify or AsyncMock(), logging.getLogger("test"), a_while=lambda: timedelta(0))


async def test_a_negotiation_asked_for_opens_once_asking_only_whether_the_watch_is_there_and_offers_on_the_answer(kept):
    claude = Claude(reads=[says(price=9900)], writes=["Hallo, ist die Uhr noch zu haben? Ich würde [BETRAG] bieten.",
                                                      "Hallo, ist die Uhr noch zu haben?", "Ich würde [BETRAG] bieten."])
    box, talking = Box(), negotiator(claude, kept)

    assert talking.ask_to_start(asked_for()) and kept.get("3535834511").status == "pending"
    assert not talking.ask_to_start(asked_for())
    await talking.start(box)
    await talking.start(box)

    assert [s.text for s in box.said] == ["Hallo, ist die Uhr noch zu haben?"]  # an amount in the first is written again
    opened = kept.get("3535834511")
    assert (opened.status, opened.conversation, opened.sent) == ("talking", "c1", [box.said[0].text])
    task = json.loads(claude.requests[0])["messages"][0]["content"][0]["text"]
    assert "The buyer has offered nothing yet" in task and "7.550" not in task

    box.seller("Ja, noch da. Preis steht ja drin.")
    await talking.follow_up(box)

    assert box.said[-1].text == "Ich würde 7.550 € bieten."  # its opening, not a step towards the seller's price
    assert kept.get("3535834511").offered == OPENING and kept.get("3535834511").opened


def test_a_first_message_from_before_it_only_asked_whether_the_watch_is_there_has_offered():
    negotiation = asked_for()
    negotiation.sent = ["Hallo, ist die Uhr noch zu haben? Ich würde 7.550 € bieten."]
    assert negotiation.opened


async def test_a_first_message_written_wrong_twice_goes_to_the_owner_who_hears_until_told(kept):
    box, notify = Box(), AsyncMock(side_effect=[RuntimeError("Discord is down"), None])
    talking = negotiator(Claude(writes=["Ich biete 8,5k.", "Ich biete [BETRAG] oder fünfhundert mehr."]), kept, notify)
    talking.ask_to_start(asked_for())

    await talking.start(box)
    await talking.tell_owner()
    await talking.tell_owner()
    await talking.tell_owner()

    assert box.said == [] and kept.get("3535834511").status == "owner"
    assert notify.await_count == 2  # once failed, once told, then no more
    channel, text = notify.await_args.args
    assert channel == "filter:42" and text.startswith("The agent hands this negotiation to you")


async def test_a_first_message_that_may_have_reached_the_seller_unseen_goes_to_the_owner_not_again(kept):
    talking = negotiator(Claude(writes=["Ist die Uhr noch zu haben?"]), kept)
    talking.ask_to_start(asked_for())

    await talking.start(Box(contact_fails=True))

    gone = kept.get("3535834511")
    assert (gone.status, gone.sent) == ("owner", ["Ist die Uhr noch zu haben?"])
    assert "could not see its first message reach the seller" in gone.notice


async def test_a_first_message_that_never_left_is_sent_as_it_was_at_the_next_look_and_at_the_third_goes_to_the_owner(kept):
    claude = Claude(writes=["Ist die Uhr noch zu haben?"])
    talking = negotiator(claude, kept)
    talking.ask_to_start(asked_for())
    refusing = Box(contact_fails=Unsent("the offer page did not load"))

    await talking.start(refusing)
    assert (kept.get("3535834511").status, kept.get("3535834511").notice) == ("pending", "")

    box = Box()
    await talking.start(box)
    assert [s.text for s in box.said] == ["Ist die Uhr noch zu haben?"] and claude.asked == ["write"]  # written once

    again = negotiator(Claude(writes=["Ist die Uhr noch zu haben?"]), kept)
    gone = asked_for()
    gone.ad_id = "1"
    again.ask_to_start(gone)
    for _ in range(3):
        await again.start(refusing)
    assert kept.get("1").status == "owner" and "took no message" in kept.get("1").notice


class Browser:
    """Chrome as the talk loop opens it: one window holding the session, on the message box's page."""

    def __init__(self, at="https://www.kleinanzeigen.de/m-nachrichten.html"):
        self.at, self.opened, self.kept = at, [], []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        pass

    async def window(self, storage_state):
        self.opened.append(storage_state)
        browser = self

        class Window:
            async def new_page(self):
                return SimpleNamespace(url=browser.at, goto=AsyncMock())

            async def storage_state(self, path):
                browser.kept.append(path)

        return Window()


async def one_look(monkeypatch, kept, box, browser, hour, notify=None):
    """keep_talking's first look, at that hour in Germany; the loop ends at its first pause."""
    monkeypatch.setattr(negotiation.chrome, "Chrome", lambda: browser)
    monkeypatch.setattr(negotiation, "Messages", lambda page: box)
    monkeypatch.setattr(negotiation.asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError))
    talking = negotiator(Claude(writes=["Ist die Uhr noch zu haben?"]), kept, notify)
    talking.ask_to_start(asked_for())
    with pytest.raises(asyncio.CancelledError):
        await negotiation.keep_talking(talking, "session.json", logging.getLogger("test"),
                                       now=lambda: datetime(2026, 10, 11, hour, 0, tzinfo=negotiation.GERMANY))


async def test_the_talk_loop_writes_by_day_with_the_owner_s_session_and_keeps_it_renewed(monkeypatch, kept):
    box, browser = Box(), Browser()

    await one_look(monkeypatch, kept, box, browser, hour=10)

    assert [s.text for s in box.said] == ["Ist die Uhr noch zu haben?"]
    assert browser.opened == browser.kept == ["session.json"]


async def test_at_night_the_agent_writes_nothing(monkeypatch, kept):
    box, browser = Box(), Browser()

    await one_look(monkeypatch, kept, box, browser, hour=23)

    assert box.said == [] and browser.opened == []


async def test_an_ended_login_is_said_to_the_owner(monkeypatch, kept):
    box, notify = Box(), AsyncMock()

    await one_look(monkeypatch, kept, box, Browser(at="https://www.kleinanzeigen.de/m-einloggen.html"), 10, notify)

    assert box.said == []
    notify.assert_awaited_once_with("filter:42", negotiation.LOGGED_OUT)


def test_a_match_worth_contacting_is_negotiated_where_its_filter_says_so(tmp_path, kept):
    monitor = WatchMonitor(log_level="ERROR")
    monitor.filter_store = FilterStore(tmp_path / "filters.json")
    monitor.filter_store.add(Filter("42", "1", "kleinanzeigen", "private", "Rolex", negotiate=True))
    monitor.filter_store.add(Filter("43", "1", "kleinanzeigen", "private", "Omega"))
    monitor._sync_filters()
    monitor.negotiator = negotiator(Claude(), kept)

    def match(key, ad_id):
        return WatchData(title="Rolex Submariner", url=f"https://www.kleinanzeigen.de/s-anzeige/{ad_id}",
                         site_name="Kleinanzeigen", site_key=key)

    worth_it = Verdict(True, "worth contacting", Decimal("10800"), Decimal("8608"), Decimal("7550"))
    monitor._negotiate_if_asked(match("filter:42", "1"), worth_it)
    monitor._negotiate_if_asked(match("filter:43", "2"), worth_it)  # its filter leaves it to the member
    monitor._negotiate_if_asked(match("filter:42", "3"), Verdict(False, "asks too much above the limit"))

    assert [(n.ad_id, n.channel, n.limit, n.offered) for n in kept.with_status("pending")] == [("1", "filter:42", 8608, 7550)]


async def test_with_nothing_to_do_the_session_is_used_once_a_day_to_keep_the_login_fresh(monkeypatch, kept):
    browser, clock = Browser(), [datetime(2026, 10, 11, 10, tzinfo=negotiation.GERMANY)]

    async def pause(seconds):  # an hour on, then a day on, then the end
        if len(steps) == 0:
            raise asyncio.CancelledError
        clock[0] += steps.pop(0)

    steps = [timedelta(hours=1), timedelta(days=1)]
    monkeypatch.setattr(negotiation.chrome, "Chrome", lambda: browser)
    monkeypatch.setattr(negotiation.asyncio, "sleep", pause)

    with pytest.raises(asyncio.CancelledError):
        await negotiation.keep_talking(negotiator(Claude(), kept), "session.json", logging.getLogger("test"), now=lambda: clock[0])

    assert browser.kept == ["session.json", "session.json"]  # the first look, and a day on; not an hour on


async def test_a_last_message_that_did_not_leave_is_sent_at_the_next_look_not_the_next_day(monkeypatch, kept):
    box, browser, notify = Box(), Browser(), AsyncMock()
    await opened(kept, box)
    agreed = kept.get("3535834511")
    agreed.terms = Terms(price=7550, bank_transfer=True, delivery="shipping", contract=True)
    kept.save(agreed)
    box.seller("Hier mein Ausweis.", pictures=1)
    box.reply = AsyncMock(side_effect=RuntimeError("the site did not answer"))
    clock = [datetime(2026, 10, 11, 10, tzinfo=negotiation.GERMANY)]

    async def pause(seconds):  # five minutes on, the site answers again; then the end
        if box.__dict__.pop("reply", None) is None:
            raise asyncio.CancelledError
        clock[0] += timedelta(seconds=seconds)

    monkeypatch.setattr(negotiation.chrome, "Chrome", lambda: browser)
    monkeypatch.setattr(negotiation, "Messages", lambda page: box)
    monkeypatch.setattr(negotiation.asyncio, "sleep", pause)
    talking = negotiator(Claude(reads=[says(id_card=True)], writes=["Danke! Der Kaufvertrag kommt gleich, dann überweise ich [BETRAG]."]),
                         kept, notify)

    with pytest.raises(asyncio.CancelledError):
        await negotiation.keep_talking(talking, "session.json", logging.getLogger("test"), now=lambda: clock[0])

    assert len(browser.opened) == 2 and box.said[-1].text == "Danke! Der Kaufvertrag kommt gleich, dann überweise ich 7.550 €."
    assert kept.get("3535834511").status == "agreed" and notify.await_count == 1


async def test_what_discord_did_not_post_the_owner_is_told_again(monkeypatch, kept):
    told = asked_for()
    told.status, told.notice = "agreed", "Agreed: send the Kaufvertrag and pay"
    kept.save(told)
    monkeypatch.setattr("monitor.DiscordApi.call", AsyncMock(return_value=(500, {"message": "500: Internal Server Error"})))

    await negotiator(Claude(), kept, WatchMonitor(log_level="ERROR")._tell_owner).tell_owner()

    assert kept.get("3535834511").notice == "Agreed: send the Kaufvertrag and pay"


async def opened(kept, box):
    """A negotiation under way: the agent asked whether the watch is there, and offered on the seller's yes."""
    talking = negotiator(Claude(reads=[says()], writes=["Ist die Uhr noch zu haben?", "Ich biete [BETRAG]."]), kept)
    talking.ask_to_start(asked_for())
    await talking.start(box)
    box.seller("Ja.")
    await talking.follow_up(box)


async def test_the_seller_s_counter_is_answered_and_nothing_new_asks_nothing(kept):
    box = Box()
    await opened(kept, box)
    quiet = Claude()
    await negotiator(quiet, kept).follow_up(box)
    assert quiet.asked == []

    box.seller("Unter 8.500 € geht nichts.")
    await negotiator(Claude(reads=[says(price=8500)], writes=["Wie wäre es mit [BETRAG]?"]), kept).follow_up(box)

    assert box.said[-1].text == "Wie wäre es mit 8.000 €?"
    assert kept.get("3535834511").offered == 8000


async def test_the_owner_hears_once_all_is_agreed_and_the_id_card_shown(kept):
    box, notify = Box(), AsyncMock()
    await opened(kept, box)
    box.seller("Ok, 7.550 € passt. Überweisung, Versand und Kaufvertrag sind ok.")
    await negotiator(Claude(reads=[says(accepts_offer=True, bank_transfer=True, delivery="shipping", contract=True)],
                            writes=["Super, [BETRAG] passt! Schicken Sie mir noch ein Foto Ihres Ausweises für den Kaufvertrag?"]),
                     kept).follow_up(box)
    assert kept.get("3535834511").status == "talking"
    assert box.said[-1].text.startswith("Super, 7.550 € passt!")  # an agreed price is named again with the rest

    box.seller("Hier mein Ausweis.", pictures=1)
    talking = negotiator(Claude(reads=[says(id_card=True)], writes=["Danke! Der Kaufvertrag kommt gleich, dann überweise ich [BETRAG]."]),
                         kept, notify)
    await talking.follow_up(box)
    await talking.tell_owner()

    assert box.said[-1].text == "Danke! Der Kaufvertrag kommt gleich, dann überweise ich 7.550 €."
    assert kept.get("3535834511").status == "agreed"
    channel, text = notify.await_args.args
    assert channel == "filter:42" and "7.550 €" in text and "shipping" in text and "Kaufvertrag" in text


async def test_a_seller_is_answered_a_while_after_they_wrote_not_at_once(kept):
    box = Box()
    await opened(kept, box)
    box.seller("Unter 8.500 € geht nichts.")
    claude = Claude(reads=[says(price=8500)], writes=["Wie wäre es mit [BETRAG]?"])
    talking = Negotiator(claude, kept, AsyncMock(), logging.getLogger("test"), a_while=lambda: timedelta(minutes=10))

    await talking.follow_up(box)
    box.seller("Und?")  # the seller writes again meanwhile: the answer keeps its time
    await talking.follow_up(box)
    waiting = kept.get("3535834511")
    assert claude.asked == [] and box.said[-1].text == "Und?"
    assert timedelta(minutes=9) < datetime.fromisoformat(waiting.due) - datetime.now(negotiation.GERMANY) <= timedelta(minutes=10)

    waiting.due = (datetime.now(negotiation.GERMANY) - timedelta(seconds=1)).isoformat()
    kept.save(waiting)
    await talking.follow_up(box)

    assert box.said[-1].text == "Wie wäre es mit 8.000 €?" and kept.get("3535834511").due == ""


def test_the_while_an_answer_waits_is_drawn_anew_each_time_within_minutes():
    talking = Negotiator(Claude(), None, AsyncMock(), logging.getLogger("test"))
    waits = {talking.a_while() for _ in range(20)}

    assert len(waits) > 1 and all(timedelta(minutes=2) <= wait <= timedelta(minutes=15) for wait in waits)


def asked_to_write(claude):
    """What the AI was given to write the latest draft from."""
    return json.loads(claude.requests[-1])["messages"][0]["content"][0]["text"]


async def test_a_draft_saying_again_what_an_earlier_message_said_is_written_anew_told_what(kept):
    box = Box()
    await opened(kept, box)
    box.seller("Unter 8.500 € geht nichts.")
    claude = Claude(reads=[says(price=8500)], writes=["Ist die Uhr noch zu haben? Sonst [BETRAG].", "Wie wäre es mit [BETRAG]?"])

    await negotiator(claude, kept).follow_up(box)

    assert box.said[-1].text == "Wie wäre es mit 8.000 €?"
    assert '"ist die uhr noch" says again what the buyer wrote before' in asked_to_write(claude)


async def test_a_draft_saying_again_what_the_ad_says_is_written_anew_told_what(kept):
    box = Box()
    await opened(kept, box)
    box.seller("Unter 8.500 € geht nichts.")
    claude = Claude(reads=[says(price=8500)], writes=["Für die Submariner Date wären [BETRAG] fair.", "Wie wäre es mit [BETRAG]?"])

    await negotiator(claude, kept).follow_up(box)

    assert box.said[-1].text == "Wie wäre es mit 8.000 €?"
    assert '"submariner date" says again what the ad says' in asked_to_write(claude)


async def test_a_second_draft_saying_something_again_goes_out_all_the_same(kept):
    box = Box()
    await opened(kept, box)
    box.seller("Unter 8.500 € geht nichts.")

    await negotiator(Claude(reads=[says(price=8500)], writes=["Ich biete [BETRAG]."] * 2), kept).follow_up(box)

    assert box.said[-1].text == "Ich biete 8.000 €." and kept.get("3535834511").status == "talking"


async def test_a_draft_saying_something_again_goes_out_should_its_rewrite_be_refused(kept):
    box = Box()
    await opened(kept, box)
    box.seller("Unter 8.500 € geht nichts.")
    claude = Claude(reads=[says(price=8500)], writes=["Ist die Uhr noch zu haben? Sonst [BETRAG].", "Maximal 9.000 €."])

    await negotiator(claude, kept).follow_up(box)

    assert box.said[-1].text == "Ist die Uhr noch zu haben? Sonst 8.000 €."
    assert kept.get("3535834511").status == "talking"


async def test_a_draft_naming_a_sum_itself_is_written_anew_told_why(kept):
    box = Box()
    await opened(kept, box)
    box.seller("Unter 8.500 € geht nichts.")
    claude = Claude(reads=[says(price=8500)], writes=["8.500 € ist mir zu viel. [BETRAG]?", "Das ist mir zu viel. [BETRAG]?"])

    await negotiator(claude, kept).follow_up(box)

    assert box.said[-1].text == "Das ist mir zu viel. 8.000 €?"
    assert "not even one the seller wrote" in asked_to_write(claude)


async def test_an_answer_written_wrong_twice_goes_to_the_owner(kept):
    box = Box()
    await opened(kept, box)
    box.seller("Was ist Ihr bestes Angebot?")

    await negotiator(Claude(reads=[says()], writes=["Maximal 9.000 €.", "Bis neuntausend."]), kept).follow_up(box)

    assert box.said[-1].text == "Was ist Ihr bestes Angebot?"
    assert kept.get("3535834511").status == "owner" and "amount decided alone" in kept.get("3535834511").notice


async def test_a_settling_message_twice_leaving_a_term_unnamed_goes_to_the_owner_told_which(kept):
    box = Box()
    await opened(kept, box)
    box.seller("Ok, 7.550 passt. Überweisung und Kaufvertrag gehen klar.")
    unnamed = "Super, [BETRAG] passt! Schicken Sie mir noch ein Foto Ihres Ausweises?"

    await negotiator(Claude(reads=[says(accepts_offer=True, bank_transfer=True, contract=True)], writes=[unnamed, unnamed]),
                     kept).follow_up(box)

    gone = kept.get("3535834511")
    assert gone.status == "owner" and "the AI wrote no message naming insured shipping, or else pickup" in gone.notice


async def test_a_word_that_only_holds_a_term_s_word_does_not_name_it(kept):
    box = Box()
    await opened(kept, box)
    box.seller("Ok, 7.550 € passt, Überweisung und Versand gehen klar. Ich bin Privatperson.")

    await negotiator(Claude(reads=[says(accepts_offer=True, bank_transfer=True, delivery="shipping")],
                            writes=["Super, [BETRAG]! Ich kaufe auch als Privatperson. War das ein Vertragshändler?",
                                    "Super, [BETRAG]! Ich mache dazu immer einen kurzen Kaufvertrag, passt das?"]),
                     kept).follow_up(box)

    assert box.said[-1].text.endswith("kurzen Kaufvertrag, passt das?")


async def test_once_the_owner_writes_in_the_conversation_the_agent_stays_out(kept):
    box = Box()
    await opened(kept, box)
    box.seller("8.000?")
    box.said.append(Said(True, "Passt, mache ich selbst."))
    claude = Claude()

    await negotiator(claude, kept).follow_up(box)

    assert claude.asked == [] and kept.get("3535834511").status == "owner"


async def test_its_own_answer_shown_after_a_failed_send_is_not_taken_for_the_owner_s(kept):
    box = Box()
    await opened(kept, box)
    box.seller("Unter 8.500 € geht nichts.")

    async def sent_but_answered_at_once(conversation_id, text):
        box.said.append(Said(True, " ".join(text.split("\n"))))
        box.seller("Und mit Versand?")
        raise RuntimeError("conversation c1 does not end with the message written")

    box.reply = sent_but_answered_at_once
    await negotiator(Claude(reads=[says(price=8500)], writes=["Wie wäre es\nmit [BETRAG]?"]), kept).follow_up(box)
    del box.reply
    await negotiator(Claude(reads=[says(price=8500, question="Und mit Versand?")],
                            writes=["Versichert, im Preis. Was ginge bei Ihnen noch?"]), kept).follow_up(box)

    assert kept.get("3535834511").status == "talking"
    assert box.said[-1].text == "Versichert, im Preis. Was ginge bei Ihnen noch?"  # it keeps 8.000 €, the seller holding
    assert kept.get("3535834511").offered == 8000


async def test_an_answer_that_did_not_reach_the_seller_is_sent_again_not_decided_again(kept):
    box = Box()
    await opened(kept, box)
    box.seller("Unter 8.500 € geht nichts.")
    box.reply = AsyncMock(side_effect=RuntimeError("the site did not answer"))
    await negotiator(Claude(reads=[says(price=8500)], writes=["Wie wäre es mit [BETRAG]?"]), kept).follow_up(box)
    del box.reply
    again = Claude()

    await negotiator(again, kept).follow_up(box)

    assert again.asked == [] and box.said[-1].text == "Wie wäre es mit 8.000 €?"


async def test_a_seller_who_wrote_after_an_answer_failed_is_read_and_the_answer_taken_back(kept):
    box = Box()
    await opened(kept, box)
    box.seller("Unter 8.500 € geht nichts, und nur bar.")
    box.reply = AsyncMock(side_effect=RuntimeError("the site did not answer"))
    await negotiator(Claude(reads=[says(price=8500, bank_transfer=False)], writes=["Wie wäre es mit [BETRAG] per Überweisung?"]),
                     kept).follow_up(box)
    box.seller("Keine Antwort? Dann eben 8.200 €, aber bar.")
    del box.reply
    claude = Claude(reads=[says(price=8200, bank_transfer=False)], writes=["Für [BETRAG] gern, aber nur per Überweisung."])

    await negotiator(claude, kept).follow_up(box)

    assert [s.text for s in box.said if s.outbound] == ["Ist die Uhr noch zu haben?", "Ich biete 7.550 €.",
                                                        "Für 7.850 € gern, aber nur per Überweisung."]
    now = kept.get("3535834511")
    assert (now.status, now.offered, now.terms.asked_again) == ("talking", 7850, [])  # the refusal waits for its turn


async def test_a_refusal_an_answer_taken_back_asked_again_counts_once(kept):
    box = Box()
    await opened(kept, box)
    box.seller("7.550 € passt, aber nur bar.")
    box.reply = AsyncMock(side_effect=RuntimeError("the site did not answer"))
    await negotiator(Claude(reads=[says(accepts_offer=True, bank_transfer=False)],
                            writes=["[BETRAG] passt. Überweisung ist mir wichtig, geht das?"]), kept).follow_up(box)
    box.seller("Keine Antwort? Wie gesagt, nur bar.")
    del box.reply

    await negotiator(Claude(reads=[says(accepts_offer=True, bank_transfer=False)],
                            writes=["[BETRAG] passt. Mit Überweisung sind wir beide abgesichert, geht das?"]), kept).follow_up(box)

    now = kept.get("3535834511")
    assert (now.status, now.terms.asked_again) == ("talking", ["bank transfer"])  # asked once more, not bid farewell
    assert box.said[-1].text == "7.550 € passt. Mit Überweisung sind wir beide abgesichert, geht das?"


async def test_a_negotiation_kept_without_its_earlier_state_has_its_unsent_message_taken_back_alone(kept):
    box = Box()
    await opened(kept, box)
    box.seller("7.550 € ok, Überweisung, Versand, Kaufvertrag, hier mein Ausweis.", pictures=1)
    box.reply = AsyncMock(side_effect=RuntimeError("the site did not answer"))
    await negotiator(Claude(reads=[says(accepts_offer=True, bank_transfer=True, delivery="shipping", contract=True,
                                        id_card=True)],
                            writes=["Danke! Der Kaufvertrag kommt gleich, dann überweise ich [BETRAG]."]), kept).follow_up(box)
    older = kept.get("3535834511")
    older.before = {}
    kept.save(older)
    box.seller("Keine Antwort? Dann ist sie jetzt anderweitig verkauft.")
    del box.reply

    await negotiator(Claude(reads=[says(ended=True)]), kept).follow_up(box)

    assert kept.get("3535834511").status == "ended"


async def test_a_message_settling_a_term_names_it(kept):
    box = Box()
    await opened(kept, box)
    box.seller("Ok, 7.550 € passt, Überweisung und Versand gehen klar.")

    # The contract left out of the first message, as the real model once waived the ID card
    await negotiator(Claude(reads=[says(accepts_offer=True, bank_transfer=True, delivery="shipping")],
                            writes=["Super, [BETRAG] per Überweisung und mit Versand!",
                                    "Super, [BETRAG]! Ich mache dazu immer einen kurzen Kaufvertrag, passt das?"]),
                     kept).follow_up(box)

    assert box.said[-1].text == "Super, 7.550 €! Ich mache dazu immer einen kurzen Kaufvertrag, passt das?"



async def test_the_owner_is_told_to_pay_only_once_the_seller_has_the_agreement(kept):
    box, notify = Box(), AsyncMock()
    await opened(kept, box)
    kept_terms = kept.get("3535834511")
    kept_terms.terms = Terms(price=7550, bank_transfer=True, delivery="shipping", contract=True)
    kept.save(kept_terms)
    box.seller("Hier mein Ausweis.", pictures=1)
    box.reply = AsyncMock(side_effect=RuntimeError("the site did not answer"))
    talking = negotiator(Claude(reads=[says(id_card=True)], writes=["Danke! Der Kaufvertrag kommt gleich, dann überweise ich [BETRAG]."]),
                         kept, notify)

    await talking.follow_up(box)
    await talking.tell_owner()
    assert kept.get("3535834511").status == "closing" and notify.await_count == 0

    del box.reply
    await talking.follow_up(box)
    await talking.tell_owner()

    assert box.said[-1].text == "Danke! Der Kaufvertrag kommt gleich, dann überweise ich 7.550 €."
    assert kept.get("3535834511").status == "agreed" and notify.await_count == 1


async def test_a_seller_who_wrote_after_the_last_word_failed_is_read_before_it_ends(kept):
    box, notify = Box(), AsyncMock()
    await opened(kept, box)
    box.seller("7.550 € ok, Überweisung, Versand, Kaufvertrag, hier mein Ausweis.", pictures=1)
    box.reply = AsyncMock(side_effect=RuntimeError("the site did not answer"))
    await negotiator(Claude(reads=[says(accepts_offer=True, bank_transfer=True, delivery="shipping", contract=True,
                                        id_card=True)],
                            writes=["Danke! Der Kaufvertrag kommt gleich, dann überweise ich [BETRAG]."]), kept).follow_up(box)
    box.seller("Keine Antwort? Dann ist sie jetzt anderweitig verkauft.")
    del box.reply
    talking = negotiator(Claude(reads=[says(ended=True)]), kept, notify)

    await talking.follow_up(box)
    await talking.tell_owner()

    assert kept.get("3535834511").status == "ended" and notify.await_count == 0
    assert box.said[-1].text == "Keine Antwort? Dann ist sie jetzt anderweitig verkauft."


@pytest.mark.parametrize("words", [
    "Super, [BETRAG]! Können Sie die Uhr versichert verschicken?",
    "Super, [BETRAG]! Würden Sie sie mir versichert zuschicken? Dann ist sie am schnellsten bei mir.",
])
async def test_a_settling_message_asks_for_the_next_term_alone_named_as_people_do(kept, words):
    box = Box()
    await opened(kept, box)
    box.seller("Ok, 7.550 € passt, Überweisung geht klar.")
    claude = Claude(reads=[says(accepts_offer=True, bank_transfer=True)], writes=[words])

    await negotiator(claude, kept).follow_up(box)

    assert box.said[-1].text == words.replace("[BETRAG]", "7.550 €")
    task = json.loads(claude.requests[-1])["messages"][0]["content"][0]["text"]
    assert '("Versand")' in task and '("Kaufvertrag")' not in task and '("Ausweis")' not in task  # the next term's word


async def test_a_farewell_asks_for_nothing_more(kept):
    box = Box()
    await opened(kept, box)
    box.seller("Unter 12.000 € nicht, und nur bar.")
    kept_now = kept.get("3535834511")
    kept_now.offered = LIMIT
    kept.save(kept_now)
    claude = Claude(reads=[says(price=12000, bank_transfer=False)], writes=["Schade, da komme ich leider nicht mit."])

    await negotiator(claude, kept).follow_up(box)

    task = json.loads(claude.requests[-1])["messages"][0]["content"][0]["text"]
    assert "ask once more" not in task and kept.get("3535834511").status == "ended"


async def test_a_seller_who_writes_again_after_the_agent_let_them_go_is_answered(kept):
    box = Box()
    await opened(kept, box)
    box.seller("Unter 12.000 € nicht.")
    at_limit = kept.get("3535834511")
    at_limit.offered = LIMIT
    kept.save(at_limit)
    await negotiator(Claude(reads=[says(price=12000)], writes=["Schade, da komme ich nicht mit. Melden Sie sich gern."]),
                     kept).follow_up(box)
    assert kept.get("3535834511").status == "ended"
    quiet = Claude()
    await negotiator(quiet, kept).follow_up(box)
    assert quiet.asked == []  # its own farewell is the last word

    box.seller("Ok, dann machen wir 8.600 €.")
    claude = Claude(reads=[says(price=8600)], writes=["Prima, [BETRAG]! Passt Ihnen Überweisung?"])
    talking = negotiator(claude, kept)
    assert [n.ad_id for n in talking.waiting()] == ["3535834511"]
    await talking.follow_up(box)

    assert box.said[-1].text == "Prima, 8.600 €! Passt Ihnen Überweisung?"
    assert (kept.get("3535834511").status, kept.get("3535834511").terms.price) == ("talking", 8600)


async def test_what_the_seller_wrote_before_the_end_is_not_read_again_only_what_they_write_after(kept):
    box = Box()
    await opened(kept, box)
    box.seller("Sorry, schon verkauft.")
    await negotiator(Claude(reads=[says(ended=True)]), kept).follow_up(box)
    quiet = Claude()
    await negotiator(quiet, kept).follow_up(box)
    assert kept.get("3535834511").status == "ended" and quiet.asked == []

    box.seller("Der Käufer ist abgesprungen, noch Interesse?")
    claude = Claude(reads=[says()], writes=["Ja, gern. Was wäre Ihr Preis?"])
    await negotiator(claude, kept).follow_up(box)

    assert claude.asked == ["read", "write"] and kept.get("3535834511").status == "talking"


def test_a_seller_let_go_more_than_a_week_ago_is_no_longer_looked_for(kept):
    gone = asked_for()
    gone.status = "ended"
    kept.save(gone)
    talking = negotiator(Claude(), kept)
    assert [n.ad_id for n in talking.waiting()] == ["3535834511"]

    with kept._db:
        kept._db.execute("UPDATE negotiations SET updated = ?", ((datetime.now() - timedelta(days=8)).isoformat(timespec="seconds"),))

    assert talking.waiting() == []


@pytest.fixture
def by_hand(tmp_path, kept):
    """The monitor with one filter the member negotiates by hand and one the agent negotiates on throughout."""
    monitor = WatchMonitor(log_level="ERROR")
    monitor.filter_store = FilterStore(tmp_path / "filters.json")
    monitor.filter_store.add(Filter("42", "1", "kleinanzeigen", "private", "Rolex", negotiate=True))
    monitor.filter_store.add(Filter("43", "1", "kleinanzeigen", "private", "Omega"))
    monitor._sync_filters()
    monitor.negotiator = negotiator(Claude(), kept)
    monitor._tell_owner = AsyncMock()
    return monitor


async def press(monitor, judged):
    monitor.agent = Mock(judge=AsyncMock(return_value=judged))
    button = monitor._negotiate_button(WatchData(title="Omega", url="https://www.kleinanzeigen.de/s-anzeige/3519758108",
                                                 site_name="Kleinanzeigen", site_key="filter:43"))
    monitor._negotiate_pressed({"data": {"custom_id": button["custom_id"]}, "channel_id": "43",
                                "message": {"embeds": [{"title": "Omega Speedmaster"}]}})
    await asyncio.gather(*monitor._judging)


async def test_only_a_filter_negotiated_by_hand_has_the_button(by_hand):
    assert by_hand._negotiates_by_hand("filter:43")
    assert not by_hand._negotiates_by_hand("filter:42") and not by_hand._negotiates_by_hand("worldoftime")


async def test_the_button_starts_a_chosen_match_up_to_its_limit_whatever_it_asks(by_hand, kept):
    await press(by_hand, (Decimal("17790"), Verdict(False, "asks too much above the limit", Decimal("10800"), Decimal("8608"))))

    (asked,) = kept.with_status("pending")
    assert (asked.ad_id, asked.channel, asked.title, asked.limit, asked.offered) == (
        "3519758108", "filter:43", "Omega Speedmaster", 8608, 7550
    )
    by_hand._tell_owner.assert_awaited_once_with(
        "filter:43", "The agent negotiates on https://www.kleinanzeigen.de/s-anzeige/3519758108: "
        "it opens at 7.550 € and pays 8.608 € at most."
    )


async def test_the_button_says_why_the_agent_leaves_a_match_without_a_limit(by_hand, kept):
    await press(by_hand, (Decimal("9000"), Verdict(False, "red flags: signs of a replica")))

    assert kept.with_status("pending") == []
    by_hand._tell_owner.assert_awaited_once_with(
        "filter:43", "The agent leaves https://www.kleinanzeigen.de/s-anzeige/3519758108 alone: red flags: signs of a replica."
    )
