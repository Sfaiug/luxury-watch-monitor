"""The buying agent's negotiation: what it answers a seller by the owner's terms, and how it writes to them."""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx2
import pytest
from anthropic import AsyncAnthropic
from playwright.async_api import TimeoutError

import negotiation
from agent import Agent, Deals, Verdict
from filters import Filter, FilterStore
from kleinanzeigen_messages import Messages, Unsent
from models import WatchData
from monitor import WatchMonitor
from negotiation import Move, Negotiation, Negotiations, Negotiator, SellerSays, Terms, filled, move

LIMIT, OPENING = 8600, 7550


def says(**said):
    """Where the seller stands, as read; a price named, and not an acceptance, read as turning the offer down."""
    stated = dict(price=None, accepts_offer=False, bank_transfer=None, delivery=None, contract=None, id_card=None,
                  ended=False, red_flags=[], question=None)
    stated.update(said)
    stated.setdefault("turns_down", stated["price"] is not None and not stated["accepts_offer"])
    return SellerSays(**stated)


def test_an_offer_the_seller_accepts_is_the_price_and_the_rest_is_settled_next():
    terms = Terms()

    answer = move(LIMIT, OPENING, terms, says(accepts_offer=True), pictures=False)

    assert (answer.kind, answer.price, terms.price) == ("agreed", 7550, 7550)
    assert list(terms.open()) == ["payment by bank transfer", "insured shipping",
                                  "the purchase contract the buyer sends to sign", "a picture of the seller's ID card"]


def test_once_it_has_offered_a_price_the_seller_names_within_the_limit_is_agreed_at_once():
    answer = move(LIMIT, OPENING, Terms(), says(price=7700), False)
    assert (answer.kind, answer.price) == ("agreed", 7700)
    assert move(LIMIT, OPENING, Terms(), says(price=LIMIT), False).price == LIMIT
    assert move(8366, 8100, Terms(), says(price=8300), False) == Move("agreed", 8300, "next: payment by bank transfer")
    assert move(LIMIT, OPENING, Terms(), says(price=7000), False).price == 7000  # below the offer: theirs
    assert move(LIMIT, OPENING, Terms(), says(price=LIMIT + 1), False).kind == "offer"


@pytest.mark.parametrize("asking, limit", [(8000, 8600), (8000, 7500), (7999, 8600)])
def test_above_asking_requests_for_the_best_offer_never_raise_it_above_the_ad_or_limit(asking, limit):
    terms, offered, answers = Terms(), 7000, []
    move(limit, offered, terms, says(), False, opening=True, asking=asking)
    for _ in range(12):
        answer = move(limit, offered, terms, says(turns_down=True), False, asking=asking)
        answers.append(answer)
        if answer.price is not None:
            assert answer.price <= min(asking, limit)
            offered = answer.price
        if answer.kind == "farewell":
            break

    assert answers[0].kind == "ask"
    assert answers[-2] == Move("final", min(asking, limit) // 50 * 50, "the seller names no price")
    assert answers[-1].kind == "farewell" and terms.price is None


@pytest.mark.parametrize("accepts_offer", [False, True])
def test_above_asking_a_seller_raising_the_ad_price_is_not_agreed_even_within_the_limit(accepts_offer):
    terms = Terms()
    answer = move(39000, 28000, terms, says(price=37500, accepts_offer=accepts_offer, turns_down=True),
                  False, asking=32000)

    assert answer.kind == "offer" and answer.price <= 32000 and terms.price is None
    assert move(39000, answer.price, terms, says(price=31000), False, asking=32000).price == 31000
    raised = move(39000, answer.price, terms, says(price=31500), False, asking=32000)
    assert raised.kind == "final" and raised.price == 31000 and terms.price is None


@pytest.mark.parametrize("accepts_offer", [False, True])
def test_above_asking_accepting_an_earlier_lower_offer_agrees_at_that_sum(accepts_offer):
    terms = Terms()

    answer = move(LIMIT, 8300, terms, says(price=8050, accepts_offer=accepts_offer), False, asking=9000)

    assert answer == Move("agreed", 8050, "next: payment by bank transfer")
    assert terms.price == 8050


@pytest.mark.parametrize("opening", [False, True])
@pytest.mark.parametrize("accepts_offer, price", [(True, None), (True, 9000), (False, 8500), (False, None)])
def test_above_asking_the_limit_also_bounds_openings_acceptances_and_existing_agreements(opening, accepts_offer, price):
    terms = Terms(price=9000, bank_transfer=True, delivery="shipping", contract=True, id_card=True)

    answer = move(8000, 9000, terms, says(price=price, accepts_offer=accepts_offer, turns_down=True),
                  False, opening=opening, asking=8500)

    assert answer.price is None or answer.price <= 8000
    assert terms.price is None or terms.price <= 8000


def test_the_agent_gives_half_the_room_left_to_its_limit():
    assert move(LIMIT, OPENING, Terms(), says(price=9000), False) == Move("offer", 8050, "the seller asks 9.000 €")

    # A seller who holds out far above the limit: 8.000, 8.300, 8.450, 8.500, then the limit as the last offer
    offers, offered = [], 8000
    while offered < LIMIT:
        answer = move(LIMIT, offered, Terms(), says(price=11000), False)
        offers.append((answer.kind, answer.price))
        offered = answer.price
    assert offers == [("offer", 8300), ("offer", 8450), ("offer", 8500), ("final", LIMIT)]

    assert move(LIMIT, LIMIT, Terms(), says(price=9500), False).kind == "farewell"


@pytest.mark.parametrize("asks", [(9500, 9500, 9500, 9500), (9500, 9500, 9400, 9300)], ids=["holding", "coming down"])
def test_a_seller_who_has_not_come_down_since_its_last_offer_is_met_with_that_offer_once_in_the_negotiation(asks):
    terms, answers, offered = Terms(), [], OPENING
    for asked in asks:
        answer = move(LIMIT, offered, terms, says(price=asked), False)
        answers.append((answer.kind, answer.price))
        offered = answer.price or offered

    assert answers == [("offer", 8050), ("hold", None), ("offer", 8300), ("offer", 8450)]


def test_a_seller_repeating_the_asking_price_after_the_opening_offer_is_met_with_it_once():
    terms = Terms()
    assert move(LIMIT, OPENING, terms, says(price=9900), False, opening=True).kind == "offer"

    assert move(LIMIT, OPENING, terms, says(price=9900), False).kind == "hold"


def test_a_seller_turning_the_offer_down_with_no_price_is_asked_theirs_not_offered_the_same():
    terms = Terms()
    move(LIMIT, OPENING, terms, says(), False, opening=True)

    assert move(LIMIT, OPENING, terms, says(turns_down=True), False) == Move("ask", None, "the seller names no price")


def test_a_seller_asking_for_the_best_price_gets_three_offers_then_their_price_is_agreed():
    terms, offered = Terms(), 7350
    assert move(8366, offered, terms, says(), False, opening=True).kind == "offer"
    best = says(turns_down=True, question="Was ist dein bester Preis?")
    answers = []
    for _ in range(3):
        answer = move(8366, offered, terms, best, False)
        answers.append((answer.kind, answer.price))
        offered = answer.price or offered

    assert answers == [("ask", None), ("offer", 7850), ("offer", 8100)]
    assert move(8366, offered, terms, says(price=8300), False).price == terms.price == 8300


def test_a_seller_never_naming_a_price_gets_one_request_then_offers_up_to_the_limit_and_a_farewell():
    terms, offered, answers = Terms(), 7350, []
    move(8366, offered, terms, says(), False, opening=True)
    for _ in range(10):
        answer = move(8366, offered, terms, says(turns_down=True), False)
        answers.append((answer.kind, answer.price))
        offered = answer.price or offered
        if answer.kind == "farewell":
            break

    assert answers == [("ask", None), ("offer", 7850), ("offer", 8100), ("offer", 8200),
                       ("offer", 8250), ("final", 8350), ("farewell", None)]


ANSWERED = Move("answer", why="the seller turns its offer down no more than before")


def test_a_seller_asking_a_question_is_answered_the_offer_standing_not_taken_for_a_no():
    terms = Terms()
    move(LIMIT, OPENING, terms, says(), False, opening=True)
    shipping = says(question="Ist der Versand inbegriffen?")

    assert move(LIMIT, OPENING, terms, shipping, False) == ANSWERED
    assert (terms.price, terms.held) == (None, False)
    # Nor at its last offer, the seller having asked more before, and still asking it
    assert move(LIMIT, LIMIT, Terms(asked=9200), shipping, False) == ANSWERED
    assert move(LIMIT, LIMIT, Terms(asked=9200), says(price=9200, question="Versand inklusive?", turns_down=False),
                False) == ANSWERED


def test_a_seller_naming_no_price_now_stands_at_the_one_named_before():
    terms = Terms()
    assert move(LIMIT, OPENING, terms, says(price=9000), False) == Move("offer", 8050, "the seller asks 9.000 €")

    no = says(turns_down=True)
    assert move(LIMIT, 8050, terms, no, False).kind == "hold"
    assert move(LIMIT, 8050, terms, no, False) == Move("offer", 8300, "the seller asks 9.000 €")

    assert move(LIMIT, 8300, terms, says(price=12000), False) == Move("offer", 8450, "the seller asks 12.000 €")
    assert move(LIMIT, 8450, terms, no, False) == Move("offer", 8500, "the seller asks 12.000 €")  # their latest


def test_a_seller_still_coming_down_after_its_last_offer_hears_it_again_and_is_let_go_once_they_stop():
    terms = Terms(asked=9250)

    assert move(LIMIT, LIMIT, terms, says(price=8900), False) == Move("final", LIMIT, "the seller asks 8.900 €")
    assert move(LIMIT, LIMIT, terms, says(price=8900), False).kind == "farewell"
    assert move(LIMIT, LIMIT, Terms(asked=8800), says(price=8600), False).kind == "agreed"  # come down to it


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

    assert written[-1] == "done" and written.count("hold") == 1
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
        "settle", None, "next: insured shipping")
    assert move(LIMIT, OPENING, terms, says(delivery="shipping", contract=True, id_card=False), False) == Move(
        "settle", None, "next: a picture of the seller's ID card", ["a picture of the ID card"])


def test_a_term_the_seller_agreed_and_then_refuses_is_open_again():
    terms = Terms(price=OPENING, bank_transfer=True, delivery="shipping", contract=True, id_card=True)

    assert move(LIMIT, OPENING, terms, says(bank_transfer=False, id_card=True), True) == Move(
        "settle", None, "next: payment by bank transfer", ["bank transfer"])
    assert list(terms.open()) == ["payment by bank transfer"]


def test_the_seller_is_asked_for_one_term_at_a_time_in_turn():
    terms, asked = Terms(price=OPENING), []
    for agreed in (dict(bank_transfer=True), dict(delivery="shipping"), dict(contract=True)):
        answer = move(LIMIT, OPENING, terms, says(), False)
        asked.append((answer.kind, answer.price, answer.why))
        move(LIMIT, OPENING, terms, says(**agreed), False)

    assert asked == [("settle", None, "next: payment by bank transfer"), ("settle", None, "next: insured shipping"),
                     ("settle", None, "next: the purchase contract the buyer sends to sign")]
    assert move(LIMIT, OPENING, terms, says(), False).why == "next: a picture of the seller's ID card"


def test_before_its_first_offer_the_agent_opens_with_it_whatever_the_seller_asks():
    assert move(LIMIT, OPENING, Terms(), says(price=9500), False, opening=True) == Move("offer", OPENING, "its opening offer")
    assert move(LIMIT, OPENING, Terms(), says(price=7700), False, opening=True) == Move("offer", OPENING, "its opening offer")
    assert move(LIMIT, OPENING, Terms(), says(), False, opening=True) == Move("offer", OPENING, "its opening offer")
    assert move(LIMIT, OPENING, Terms(), says(accepts_offer=True), False, opening=True).kind == "offer"  # nothing to accept
    assert move(LIMIT, OPENING, Terms(), says(price=7000), False, opening=True) == Move("agreed", 7000, "next: payment by bank transfer")


@pytest.mark.parametrize("accepts_offer", [False, True])
@pytest.mark.parametrize("bank_transfer", [False, True])
def test_a_seller_lowering_the_agreed_price_keeps_the_lower_price(accepts_offer, bank_transfer):
    terms = Terms(price=8300, bank_transfer=bank_transfer, delivery="shipping", contract=True, id_card=True)

    answer = move(8366, 8100, terms, says(price=8250, accepts_offer=accepts_offer, id_card=True), True)

    assert terms.price == 8250
    assert answer == (Move("done", 8250, "all agreed") if bank_transfer else
                      Move("settle", None, "next: payment by bank transfer"))
    assert move(8366, 8100, terms, says(bank_transfer=True, id_card=True), True) == Move("done", 8250, "all agreed")


def test_above_asking_a_seller_raising_the_agreed_price_cannot_raise_the_ceiling():
    terms = Terms(price=OPENING, bank_transfer=True, delivery="shipping", contract=True, id_card=True)

    assert move(LIMIT, OPENING, terms, says(price=OPENING, id_card=True), True).kind == "done"  # the agreed price named again
    assert move(LIMIT, 7000, terms, says(price=9000), False).kind == "farewell"
    assert terms.price is None


def test_a_red_flag_or_a_sold_watch_ends_it_without_a_word():
    assert move(LIMIT, OPENING, Terms(), says(red_flags=["payment_or_contact_outside_kleinanzeigen"]), False).kind == "end"
    assert move(LIMIT, OPENING, Terms(), says(ended=True), False).kind == "end"


def test_all_is_agreed_once_the_id_card_is_shown_not_only_promised():
    terms = Terms(price=OPENING, bank_transfer=True, delivery="shipping", contract=True)

    assert move(LIMIT, OPENING, terms, says(id_card=True), pictures=False).kind == "settle"
    assert move(LIMIT, OPENING, terms, says(id_card=True), pictures=True) == Move("done", OPENING, "all agreed")


def test_a_seller_handing_it_over_in_person_only_is_asked_once_more_to_ship_then_left_to_the_owner():
    terms = Terms(price=OPENING, bank_transfer=True)

    first = move(LIMIT, OPENING, terms, says(delivery="pickup"), False)
    assert (first.kind, first.refused, terms.delivery) == ("settle", ["insured shipping"], None)
    assert move(LIMIT, OPENING, terms, says(delivery="pickup"), False) == Move(
        "decide", None, "the seller hands it over in person only")

    terms.in_person = False  # the owner's word: shipping only
    assert move(LIMIT, OPENING, terms, says(delivery="pickup"), False).kind == "farewell"


def test_a_watch_the_owner_picks_up_needs_the_id_card_shown_there_not_as_a_picture():
    terms = Terms(price=OPENING, bank_transfer=True, in_person=True)

    assert move(LIMIT, OPENING, terms, says(delivery="pickup", contract=True), pictures=False) == Move(
        "done", OPENING, "all agreed", pickup=True)  # agreed just now: the seller is told
    # Shipped after all, it needs the picture
    assert move(LIMIT, OPENING, terms, says(delivery="shipping"), False) == Move(
        "settle", None, "next: a picture of the seller's ID card")


def test_a_pickup_the_owner_agreed_to_is_told_in_the_next_answer_even_a_new_offer():
    terms = Terms(bank_transfer=True, in_person=True)

    assert move(LIMIT, OPENING, terms, says(delivery="pickup", price=9000), False) == Move(
        "offer", 8050, "the seller asks 9.000 €", pickup=True)
    assert move(LIMIT, 8050, terms, says(accepts_offer=True), False).pickup is False  # told once


def test_a_pickup_agreed_before_the_owner_had_a_word_in_it_is_asked_to_ship():
    terms = Terms(price=OPENING, bank_transfer=True, delivery="pickup", contract=True)  # kept before 13 Oct 2026

    assert move(LIMIT, OPENING, terms, says(), False) == Move("settle", None, "next: insured shipping")


TITLE = "Rolex Submariner Date 126610LN"


@pytest.mark.parametrize("written, sent", [
    ("Ist die Uhr noch da? Ich biete [BETRAG].", "Ist die Uhr noch da? Ich biete 8.000 €."),
    ("Ist die Submariner 126610LN noch da? Abholung ginge um 14 Uhr, [BETRAG]?", None),
    ("Für die 126610LN: [BETRAG].", None),  # even the title's reference
    ("Ich würde [BETRAG] € zahlen, oder € [BETRAG]?", None),  # twice
    ("Ich würde [BETRAG] € zahlen.", "Ich würde 8.000 € zahlen."),  # its sign is the amount's
    ("Abholung ginge um 14.30 Uhr, [BETRAG]? Sie hat 40,5 mm.", None),
    ("Über 40 komme ich nicht. [BETRAG]?", None),
    ("Ich lege noch 50 drauf: [BETRAG].", None),
    ("Ich melde mich in 2 Tagen. [BETRAG]?", None),
    ("Noch 0 Fragen, [BETRAG] passt.", None),
    ("Ich melde mich in ٢ Tagen. [BETRAG]?", None),
    ("Ich melde mich in ² Tagen. [BETRAG]?", None),
    ("Ich melde mich in zwei Tagen. [BETRAG]?", "Ich melde mich in zwei Tagen. 8.000 €?"),
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
def test_no_digit_in_the_ai_s_own_words_when_the_code_writes_the_amount_in(written, sent):
    assert filled(written, 8000) == sent


@pytest.mark.parametrize("written, sent", [
    ("Schade, dann passt es leider nicht.", "Schade, dann passt es leider nicht."),
    ("Schade, [BETRAG] ist zu wenig.", None),
    ("Über 40 komme ich nicht.", None),
    ("Ich lege noch 50 drauf.", None),
    ("8300 wäre okay.", None),
    ("Ich melde mich in 2 Tagen.", None),
    ("Ich melde mich in zwei Tagen.", "Ich melde mich in zwei Tagen."),
])
def test_no_digit_in_a_message_with_no_amount_decided(written, sent):
    assert filled(written, None) == sent


@dataclass
class Said:
    outbound: bool
    text: str
    attachments: list = field(default_factory=list)


class Box:
    """The owner's message box, with one seller in it."""

    def __init__(self, contact_fails=False):
        self.said, self.contact_fails = [], contact_fails

    async def contact(self, ad_id, text, *, before_send=lambda before: None):
        if isinstance(self.contact_fails, Unsent):
            raise self.contact_fails
        before_send(len(self.said))
        if self.contact_fails is True:
            raise RuntimeError("the page did not answer")
        if self.contact_fails:
            raise self.contact_fails
        self.said.append(Said(True, text))
        return "c1"

    async def conversation(self, conversation_id):
        return SimpleNamespace(id=conversation_id, messages=list(self.said), buyer="Jonas M.")

    async def reply(self, conversation_id, text):
        self.said.append(Said(True, text))

    def seller(self, text, pictures=0):
        self.said.append(Said(False, text, [f"https://chat/picture-{len(self.said)}-{p}" for p in range(pictures)]))

    async def picture(self, url):
        return {"media_type": "image/jpeg", "data": "cGljdHVyZQ=="}


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


async def test_a_first_message_written_wrong_each_time_goes_to_the_owner_who_hears_until_told(kept):
    box, notify = Box(), AsyncMock(side_effect=[RuntimeError("Discord is down"), None])
    wrong = ["Ich biete 8,5k.", "Ich biete [BETRAG] oder fünfhundert mehr.", "Hallo, 8.000 €?"]
    talking = negotiator(Claude(writes=wrong), kept, notify)
    talking.ask_to_start(asked_for())

    await talking.start(box)
    await talking.tell_owner()
    await talking.tell_owner()
    await talking.tell_owner()

    assert box.said == [] and kept.get("3535834511").status == "owner"
    assert notify.await_count == 2  # once failed, once told, then no more
    channel, text = notify.await_args.args[:2]
    assert channel == "filter:42" and text.startswith("The agent hands this negotiation to you")


@pytest.mark.parametrize("earlier", [None, [], [Said(True, "Ist die Uhr noch zu haben?")]])
@pytest.mark.parametrize("click_times_out", [False, True])
async def test_a_first_message_shown_later_counts_as_sent_without_sending_twice(kept, earlier, click_times_out):
    page = SimpleNamespace(goto=AsyncMock(), fill=AsyncMock(), click=AsyncMock(), wait_for_selector=AsyncMock(), close=AsyncMock(),
                           add_init_script=AsyncMock(), evaluate=AsyncMock(return_value=False))

    async def click(selector):
        if click_times_out:
            raise TimeoutError("the click handler is still running after submission")

    page.click.side_effect = click
    box = Messages(SimpleNamespace(context=SimpleNamespace(new_page=AsyncMock(return_value=page))))
    box.bought = AsyncMock(return_value="c1" if earlier is not None else None)
    box.conversation = AsyncMock(return_value=SimpleNamespace(messages=earlier or []))
    box.reply = AsyncMock()
    notify = AsyncMock()
    claude = Claude(writes=["Ist die Uhr noch zu haben?"])
    talking = negotiator(claude, kept, notify)
    talking.ask_to_start(asked_for())

    await talking.start(box)
    await talking.follow_up(box)
    await talking.tell_owner()

    waiting = kept.get("3535834511")
    assert (waiting.status, waiting.sent, waiting.notice) == ("opening", ["Ist die Uhr noch zu haben?"], "")
    assert waiting.seen == len(earlier or [])
    assert [n.ad_id for n in talking.waiting()] == [waiting.ad_id]
    notify.assert_not_awaited()

    # A fresh negotiator reads the saved attempt. The seller may already have answered it.
    talking = negotiator(Claude(), kept, notify)
    box.bought.return_value = "c1"
    box.conversation.return_value.messages = (earlier or []) + [Said(True, "Ist die Uhr\nnoch zu haben?"), Said(False, "Ja.")]
    await talking.start(box)
    await talking.start(box)
    await talking.tell_owner()

    opened = kept.get("3535834511")
    assert (opened.status, opened.conversation, opened.sent) == ("talking", "c1", waiting.sent)
    assert claude.asked == ["write"]
    page.click.assert_awaited_once()
    box.reply.assert_not_awaited()
    notify.assert_not_awaited()


@pytest.mark.parametrize("shows_message", [False, True])
async def test_an_interrupted_first_message_keeps_its_boundary_until_shown_later(tmp_path, shows_message):
    path = tmp_path / "deals.sqlite3"
    kept = Negotiations(path)
    text = "Ist die Uhr noch zu haben?"
    earlier = [Said(True, text)]
    page = SimpleNamespace(goto=AsyncMock(), fill=AsyncMock(), click=AsyncMock(),
                           wait_for_selector=AsyncMock(side_effect=asyncio.CancelledError), close=AsyncMock(),
                           add_init_script=AsyncMock(), evaluate=AsyncMock())
    box = Messages(SimpleNamespace(context=SimpleNamespace(new_page=AsyncMock(return_value=page))))
    box.bought = AsyncMock(return_value="c1")
    box.conversation = AsyncMock(return_value=SimpleNamespace(messages=earlier))
    box.reply = AsyncMock()
    notify = AsyncMock()
    talking = negotiator(Claude(writes=[text]), kept, notify)
    talking.ask_to_start(asked_for())

    try:
        with pytest.raises(asyncio.CancelledError):
            await talking.start(box)
        interrupted = kept.get("3535834511")
        assert (interrupted.status, interrupted.seen, interrupted.notice) == ("opening", len(earlier), "")
    finally:
        kept.close()

    kept = Negotiations(path)
    try:
        talking = negotiator(Claude(), kept, notify)
        box.conversation.return_value.messages = earlier + ([Said(True, text)] if shows_message else [])
        await talking.start(box)
        await talking.tell_owner()

        result = kept.get("3535834511")
        assert result.status == ("talking" if shows_message else "owner")
        assert result.conversation == ("c1" if shows_message else "")
        assert notify.await_count == (0 if shows_message else 1)
        page.click.assert_awaited_once()
        box.reply.assert_not_awaited()
    finally:
        kept.close()


@pytest.mark.parametrize("later", [[], [Said(False, "Ja.")]])
async def test_an_old_identical_first_message_is_not_the_one_to_be_shown_later(kept, later):
    text = "Ist die Uhr noch zu haben?"
    earlier = [Said(True, text)]
    page = SimpleNamespace(goto=AsyncMock(), fill=AsyncMock(), click=AsyncMock(), wait_for_selector=AsyncMock(), close=AsyncMock(),
                           add_init_script=AsyncMock(), evaluate=AsyncMock())
    box = Messages(SimpleNamespace(context=SimpleNamespace(new_page=AsyncMock(return_value=page))))
    box.bought = AsyncMock(return_value="c1")
    box.conversation = AsyncMock(return_value=SimpleNamespace(messages=earlier))
    box.reply = AsyncMock()
    notify = AsyncMock()
    talking = negotiator(Claude(writes=[text]), kept, notify)
    talking.ask_to_start(asked_for())

    await talking.start(box)
    assert kept.get("3535834511").status == "opening"

    # Only messages after submission can confirm it, even if the conversation grew.
    talking = negotiator(Claude(), kept, notify)
    box.conversation.return_value.messages = earlier + later
    await talking.start(box)
    assert kept.get("3535834511").status == "owner"
    await talking.follow_up(box)
    await talking.tell_owner()

    assert "could not see its first message reach the seller" in notify.await_args.args[1]
    page.click.assert_awaited_once()
    box.reply.assert_not_awaited()
    notify.assert_awaited_once()


@pytest.mark.parametrize("shown", [None, [], [Said(True, "A different message")], [Said(False, "Ist die Uhr noch zu haben?")]])
async def test_a_first_message_not_shown_later_goes_to_the_owner_without_sending_again(kept, shown):
    talking = negotiator(Claude(writes=["Ist die Uhr noch zu haben?"]), kept)
    talking.ask_to_start(asked_for())
    box = Box(contact_fails=True)
    box.contact = AsyncMock(wraps=box.contact)
    box.bought = AsyncMock(return_value="c1" if shown is not None else None)
    box.said = shown or []

    await talking.start(box)
    await talking.follow_up(box)
    await talking.tell_owner()
    assert kept.get("3535834511").status == "opening"
    box.bought.assert_not_awaited()
    talking.notify.assert_not_awaited()

    await talking.start(box)
    await talking.start(box)

    gone = kept.get("3535834511")
    assert (gone.status, gone.sent) == ("owner", ["Ist die Uhr noch zu haben?"])
    assert "could not see its first message reach the seller" in gone.notice
    box.contact.assert_awaited_once()
    await talking.tell_owner()
    await talking.tell_owner()
    talking.notify.assert_awaited_once()


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

    box.seller("Unter 9.500 € geht nichts.")
    await negotiator(Claude(reads=[says(price=9500)], writes=["Wie wäre es mit [BETRAG]?"]), kept).follow_up(box)

    assert box.said[-1].text == "Wie wäre es mit 8.050 €?"
    assert kept.get("3535834511").offered == 8050


async def test_above_asking_festpreis_uses_the_ad_price_in_the_reading_and_the_agreement(kept):
    box = Box()
    await opened(kept, box)
    current = kept.get("3535834511")
    current.asking = 8000
    kept.save(current)
    box.seller("Festpreis, wie in der Anzeige.")
    claude = Claude(reads=[says(price=8000)], writes=["[BETRAG] passt. Geht Überweisung?"])

    await negotiator(claude, kept).follow_up(box)

    request = json.loads(claude.requests[0])
    assert "The ad's asking price: 8.000 €" in request["messages"][0]["content"][0]["text"]
    assert "Festpreis" in request["system"]
    assert box.said[-1].text == "8.000 € passt. Geht Überweisung?"
    assert kept.get(current.ad_id).terms.price == 8000


async def test_above_asking_the_lowest_chat_price_survives_a_failed_reply_and_restart(kept):
    box = Box()
    await opened(kept, box)
    box.seller("8.050 wären ok.")
    box.reply = AsyncMock(side_effect=RuntimeError("the site did not answer"))
    await negotiator(Claude(reads=[says(price=8050)], writes=["[BETRAG] passt. Geht Überweisung?"]), kept).follow_up(box)
    assert kept.get("3535834511").terms.lowest == 8050
    box.seller("Jetzt möchte ich doch 8.300.")
    del box.reply

    await negotiator(Claude(reads=[says(price=8300)], writes=["Für [BETRAG] würde ich sie nehmen."]), kept).follow_up(box)

    current = kept.get("3535834511")
    assert current.terms.lowest == 8050 and current.terms.price is None
    assert current.offered == 7800 and box.said[-1].text == "Für 7.800 € würde ich sie nehmen."


async def test_above_asking_the_observed_price_survives_failed_drafting_and_a_database_restart(kept, tmp_path, monkeypatch):
    box = Box()
    await opened(kept, box)
    current = kept.get("3535834511")
    current.asking = 9000
    kept.save(current)
    box.seller("8.050 wären ok.")
    monkeypatch.setattr(negotiation, "ask", AsyncMock(side_effect=[says(price=8050, bank_transfer=False),
                                                                 RuntimeError("temporary AI outage while drafting")]))

    await negotiator(None, kept).follow_up(box)

    observed = kept.get(current.ad_id)
    assert observed.terms.lowest == 8050
    assert observed.terms.price is None and observed.terms.asked_again == []
    assert observed.offered == OPENING and observed.sent == current.sent
    kept.close()
    restarted = Negotiations(tmp_path / "deals.sqlite3")
    box.seller("Jetzt doch 8.300.")
    monkeypatch.setattr(negotiation, "ask", AsyncMock(side_effect=[says(price=8300),
                                                                 negotiation.Written(message="Für [BETRAG] würde ich sie nehmen.")]))

    await negotiator(None, restarted).follow_up(box)

    current = restarted.get(current.ad_id)
    assert current.terms.lowest == 8050 and current.terms.price is None
    assert current.offered == 7800 and box.said[-1].text == "Für 7.800 € würde ich sie nehmen."
    restarted.close()


async def test_above_asking_a_delayed_read_keeps_the_chat_minimum_separate_from_the_current_ask(kept):
    box = Box()
    await opened(kept, box)
    current = kept.get("3535834511")
    current.asking = 9000
    kept.save(current)
    box.seller("8.050 wären ok.")
    box.seller("Jetzt doch 8.300.")
    claude = Claude(reads=[says(price=8300, lowest=8050)], writes=["[BETRAG] passt. Geht Überweisung?"])

    await negotiator(claude, kept).follow_up(box)

    request = json.loads(claude.requests[0])
    assert "lowest" in request["output_config"]["format"]["schema"]["properties"]
    assert "entire conversation" in request["system"]
    read = request["messages"][0]["content"][0]["text"]
    assert "8.050 wären ok." in read and "Jetzt doch 8.300." in read
    current = kept.get(current.ad_id)
    assert current.terms.lowest == 8050 and current.terms.asked == 8300
    assert current.terms.price is None and current.offered == 7800
    assert box.said[-1].text == "7.800 € passt. Geht Überweisung?"


async def test_the_owner_hears_once_all_is_agreed_and_the_id_card_shown(kept):
    box, notify = Box(), AsyncMock()
    await opened(kept, box)
    box.seller("Ok, 7.550 € passt. Überweisung, Versand und Kaufvertrag sind ok.")
    await negotiator(Claude(reads=[says(accepts_offer=True, bank_transfer=True, delivery="shipping", contract=True)],
                            writes=["Super, [BETRAG] passt! Schickst du mir noch ein Foto deines Ausweises für den Kaufvertrag?"]),
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
    channel, text = notify.await_args.args[:2]
    assert channel == "filter:42" and "7.550 €" in text and "shipping" in text and "Kaufvertrag" in text


@pytest.mark.parametrize("pictures, id_card, previously_seen, buyer_picture", [
    (1, None, False, False),  # a watch picture captioned as an ID is still a watch picture
    (0, True, False, False),  # a promise or an unsupported reading cannot substitute for a picture
    (0, True, False, True),  # a picture from the buyer cannot count as the seller's ID
    (0, None, True, False),  # an old, text-only confirmation needs visual evidence too
    (1, None, True, False),
])
async def test_id_card_seen_requires_visual_evidence_from_the_seller(
        kept, pictures, id_card, previously_seen, buyer_picture):
    box, notify = Box(), AsyncMock()
    await opened(kept, box)
    ready = kept.get("3535834511")
    ready.terms = Terms(price=7550, bank_transfer=True, delivery="shipping", contract=True, id_card=previously_seen)
    kept.save(ready)
    if buyer_picture:
        box.said[0].attachments = ["https://chat/buyer-picture"]
    box.seller("Hier mein Ausweis.", pictures=pictures)
    box.picture = AsyncMock(wraps=box.picture)
    claude = Claude(reads=[says(id_card=id_card)], writes=["Schickst du mir bitte ein Foto deines Ausweises?"])
    talking = negotiator(claude, kept, notify)

    await talking.follow_up(box)
    await talking.tell_owner()

    assert kept.get(ready.ad_id).status == "talking"
    assert not kept.get(ready.ad_id).terms.id_card
    assert notify.await_count == 0
    assert box.picture.await_count == pictures
    request = json.loads(claude.requests[0])
    assert "visibly shows an ID card" in request["system"]
    assert len([block for block in request["messages"][0]["content"] if block["type"] == "image"]) == pictures


async def test_id_card_seen_before_it_was_asked_for_counts_and_only_the_chat_link_is_kept(kept):
    box, notify = Box(), AsyncMock()
    await opened(kept, box)
    # The seller's first reply contained uncaptioned pictures, before even the buyer's first price offer.
    urls = ["https://chat/watch-picture", "https://chat/id-picture"]
    box.said[1].text, box.said[1].attachments = "", urls
    sources = [{"media_type": "image/png", "data": "d2F0Y2g="},
               {"media_type": "image/jpeg", "data": "SUQgY2FyZA=="}]
    box.picture = AsyncMock(side_effect=lambda url: sources[urls.index(url)])
    box.seller("7.550 € passt. Überweisung und versicherter Versand auch.")
    claude = Claude(reads=[says(accepts_offer=True, bank_transfer=True, delivery="shipping", id_card=True),
                          says(contract=True, id_card=True)],
                    writes=["[BETRAG] passt. Machen wir einen Kaufvertrag?",
                            "Danke! Der Kaufvertrag kommt gleich, dann überweise ich [BETRAG]."])
    talking = negotiator(claude, kept, notify)

    await talking.follow_up(box)
    assert kept.get("3535834511").terms.id_card
    box.seller("Ja, Kaufvertrag passt.")  # no new picture since the buyer wrote
    await talking.follow_up(box)
    await talking.tell_owner()

    assert kept.get("3535834511").status == "agreed"
    assert notify.await_count == 1
    assert "https://www.kleinanzeigen.de/m-nachrichten.html?conversationId=c1" in notify.await_args.args[1]
    requests = [json.loads(request) for request in claude.requests]
    for request in (requests[0], requests[2]):
        assert request["messages"][0]["content"][1:] == [
            {"type": "image", "source": {"type": "base64", **source}} for source in sources
        ]
    for request in (requests[1], requests[3]):
        assert all(block["type"] == "text" for block in request["messages"][0]["content"])
    stored = kept._db.execute("SELECT kept FROM negotiations").fetchone()[0]
    for private in urls + [source["data"] for source in sources]:
        assert private not in stored
        assert all(private not in json.dumps(request) for request in (requests[1], requests[3]))
        assert private not in notify.await_args.args[1]


async def test_id_card_seen_unreadable_pictures_cannot_complete_the_purchase(kept):
    box, notify = Box(), AsyncMock()
    await opened(kept, box)
    ready = kept.get("3535834511")
    ready.terms = Terms(price=7550, bank_transfer=True, delivery="shipping", contract=True)
    kept.save(ready)
    box.seller("Hier mein Ausweis.", pictures=1)
    box.picture = AsyncMock(side_effect=RuntimeError("Could not read a chat picture"))
    claude = Claude()
    talking = negotiator(claude, kept, notify)

    await talking.follow_up(box)
    await talking.tell_owner()

    assert claude.requests == [] and notify.await_count == 0
    assert kept.get(ready.ad_id).status == "talking" and not kept.get(ready.ad_id).terms.id_card
    assert box.said[-1].text == "Hier mein Ausweis."


def instructed(claude):
    """What the AI was told to write the latest draft as."""
    return json.loads(claude.requests[-1])["system"]


async def test_a_seller_handing_it_over_in_person_only_is_asked_to_ship_it_with_a_reason(kept):
    box = Box()
    await opened(kept, box)
    box.seller("Ok, 7.550 € passt, Überweisung geht klar. Aber nur Abholung.")
    claude = Claude(reads=[says(accepts_offer=True, bank_transfer=True, delivery="pickup")],
                    writes=["Super, [BETRAG] passt! Ich kaufe meine Uhren immer versichert verschickt, ginge das?"])

    await negotiator(claude, kept).follow_up(box)

    assert kept.get("3535834511").terms.delivery is None
    assert "The seller refuses insured shipping" in asked_to_write(claude)
    assert "does not come by to see or pick them up" in instructed(claude)
    assert "handover in person" not in instructed(claude)


async def insisting_on_a_handover(kept, box, notify):
    """A seller asked once more to ship the watch, refusing again: the owner is asked, with a button for each choice."""
    await opened(kept, box)
    asking = kept.get("3535834511")
    asking.terms = Terms(price=OPENING, bank_transfer=True, asked_again=["insured shipping"])
    kept.save(asking)
    box.seller("Nein, wirklich nur Abholung.")
    talking = negotiator(Claude(reads=[says(delivery="pickup")]), kept, notify)
    await talking.follow_up(box)
    await talking.tell_owner()
    await talking.follow_up(box)  # the seller waits while the owner decides
    return talking


async def test_a_seller_insisting_on_a_handover_in_person_waits_for_the_owner_s_word(kept):
    box, notify = Box(), AsyncMock()
    talking = await insisting_on_a_handover(kept, box, notify)

    assert kept.get("3535834511").status == "deciding" and box.said[-1].text == "Nein, wirklich nur Abholung."
    channel, text, buttons = notify.await_args.args
    assert channel == "filter:42" and "hands it over in person only" in text and "3535834511" in text
    assert [label for label, _ in buttons] == ["Pick it up", "Shipping only"]
    assert talking.pressed("negotiate:3535834511") is None  # a match's own button, not a decision's


async def test_once_the_owner_says_pick_it_up_the_deal_goes_on_the_seller_to_show_their_id_card_there(kept):
    box, notify = Box(), AsyncMock()
    await insisting_on_a_handover(kept, box, notify)
    (_, pickup), _ = notify.await_args.args[2]
    claude = Claude(reads=[says(delivery="pickup", contract=True)],
                    writes=["Gut, dann hole ich sie bei dir ab und überweise [BETRAG] direkt vor Ort."])
    talking = negotiator(claude, kept, notify)

    assert talking.pressed(pickup) == "Pick it up: the agent goes on from there with the seller."
    assert talking.pressed(pickup) == "There is nothing to decide on this one any more."
    await talking.follow_up(box)
    await talking.tell_owner()

    assert kept.get("3535834511").status == "agreed"
    assert "needs no picture of the ID card then" in instructed(claude)
    assert "for this one he makes an exception" in instructed(claude)  # having said he buys shipped
    assert "pays at the handover, where they show him their ID card" in asked_to_write(claude)
    assert "the buyer comes to the seller for the watch, as an exception" in asked_to_write(claude)
    channel, text, buttons = notify.await_args.args
    assert "pickup" in text and "shows their ID card at the handover. Send the Kaufvertrag, and pay there" in text
    assert buttons == []


async def test_once_the_owner_holds_to_shipping_the_seller_is_bid_farewell(kept):
    box, notify = Box(), AsyncMock()
    await insisting_on_a_handover(kept, box, notify)
    _, (_, ship) = notify.await_args.args[2]
    talking = negotiator(Claude(reads=[says(delivery="pickup")],
                                writes=["Schade, abholen kann ich sie leider nicht. Melde dich gern, falls doch."]), kept)

    talking.pressed(ship)
    await talking.follow_up(box)

    assert kept.get("3535834511").status == "ended"
    assert box.said[-1].text == "Schade, abholen kann ich sie leider nicht. Melde dich gern, falls doch."


async def test_the_owner_is_asked_with_buttons_that_answer_the_agent(monkeypatch, kept):
    posted = AsyncMock(return_value=(200, {"id": "1"}))
    monkeypatch.setattr("monitor.DiscordApi.call", posted)
    monitor = WatchMonitor(log_level="ERROR")
    asking = asked_for()
    asking.status, asking.notice = "deciding", "Pick it up yourself, or hold to shipping?"
    kept.save(asking)
    monitor.negotiator = negotiator(Claude(), kept, monitor._tell_owner)

    await monitor.negotiator.tell_owner()

    method, path, message = posted.await_args.args
    assert (method, path, message["content"]) == ("POST", "/channels/42/messages", "Pick it up yourself, or hold to shipping?")
    pickup, ship = message["components"][0]["components"]
    assert (pickup["label"], ship["label"]) == ("Pick it up", "Shipping only")
    assert monitor._negotiate_pressed({"data": {"custom_id": ship["custom_id"]}}).startswith("Shipping only")
    assert (kept.get("3535834511").status, kept.get("3535834511").terms.in_person) == ("talking", False)


async def test_a_button_pressed_while_its_notice_is_posted_holds(kept):
    asking = asked_for()
    asking.status, asking.notice = "deciding", "Pick it up yourself, or hold to shipping?"
    kept.save(asking)

    async def notify(channel, text, buttons):
        talking.pressed(buttons[0][1])  # the owner, quicker than the post's answer

    talking = negotiator(Claude(), kept, notify)
    await talking.tell_owner()

    decided = kept.get("3535834511")
    assert (decided.status, decided.terms.in_person, decided.notice) == ("talking", True, "")


async def test_a_seller_is_answered_a_while_after_they_wrote_not_at_once(kept):
    box = Box()
    await opened(kept, box)
    box.seller("Unter 9.500 € geht nichts.")
    claude = Claude(reads=[says(price=9500)], writes=["Wie wäre es mit [BETRAG]?"])
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

    assert box.said[-1].text == "Wie wäre es mit 8.050 €?" and kept.get("3535834511").due == ""


def test_the_while_an_answer_waits_is_drawn_anew_each_time_within_minutes():
    talking = Negotiator(Claude(), None, AsyncMock(), logging.getLogger("test"))
    waits = {talking.a_while() for _ in range(20)}

    assert len(waits) > 1 and all(timedelta(minutes=2) <= wait <= timedelta(minutes=15) for wait in waits)


def asked_to_write(claude):
    """What the AI was given to write the latest draft from."""
    return json.loads(claude.requests[-1])["messages"][0]["content"][0]["text"]


async def test_a_draft_saying_again_what_an_earlier_message_said_is_written_anew_told_what_and_logged(kept, caplog):
    box = Box()
    await opened(kept, box)
    box.seller("Unter 9.500 € geht nichts.")
    claude = Claude(reads=[says(price=9500)], writes=["Ist die Uhr noch zu haben? Sonst [BETRAG].", "Wie wäre es mit [BETRAG]?"])

    await negotiator(claude, kept).follow_up(box)

    assert box.said[-1].text == "Wie wäre es mit 8.050 €?"
    assert '"ist die uhr noch" says again what the buyer wrote before' in asked_to_write(claude)
    assert [r.message.rsplit(": ", 1)[1] for r in caplog.records if "draft refused" in r.message] == [
        "Ist die Uhr noch zu haben? Sonst [BETRAG]."]


async def test_the_buyer_writes_knowing_the_name_kleinanzeigen_shows_the_seller(kept):
    box = Box()
    await opened(kept, box)
    box.seller("Ja, noch da. Wie heißt du eigentlich?")
    claude = Claude(reads=[says(question="Wie heißt du?")], writes=["Ich bin Jonas. Was wäre denn dein Preis?"])

    await negotiator(claude, kept).follow_up(box)

    assert "The buyer's name, as Kleinanzeigen shows it to the seller: Jonas M." in asked_to_write(claude)
    assert box.said[-1].text == "Ich bin Jonas. Was wäre denn dein Preis?"


async def test_a_draft_saying_again_what_the_ad_says_is_written_anew_told_what(kept):
    box = Box()
    await opened(kept, box)
    box.seller("Unter 9.500 € geht nichts.")
    claude = Claude(reads=[says(price=9500)], writes=["Für die Submariner Date wären [BETRAG] fair.", "Wie wäre es mit [BETRAG]?"])

    await negotiator(claude, kept).follow_up(box)

    assert box.said[-1].text == "Wie wäre es mit 8.050 €?"
    assert '"submariner date" says again what the ad says' in asked_to_write(claude)


async def test_a_second_draft_saying_something_again_goes_out_all_the_same(kept):
    box = Box()
    await opened(kept, box)
    box.seller("Unter 9.500 € geht nichts.")

    await negotiator(Claude(reads=[says(price=9500)], writes=["Ich biete [BETRAG]."] * 2), kept).follow_up(box)

    assert box.said[-1].text == "Ich biete 8.050 €." and kept.get("3535834511").status == "talking"


async def test_a_draft_saying_something_again_goes_out_should_its_rewrite_be_refused(kept):
    box = Box()
    await opened(kept, box)
    box.seller("Unter 9.500 € geht nichts.")
    claude = Claude(reads=[says(price=9500)], writes=["Ist die Uhr noch zu haben? Sonst [BETRAG].", "Maximal 9.000 €."])

    await negotiator(claude, kept).follow_up(box)

    assert box.said[-1].text == "Ist die Uhr noch zu haben? Sonst 8.050 €."
    assert kept.get("3535834511").status == "talking"


@pytest.mark.parametrize("title, written", [
    (TITLE, "8.500 € ist mir zu viel. [BETRAG]?"),
    (TITLE, "Über 40 komme ich nicht. [BETRAG]?"),
    (TITLE, "Ich lege noch 50 drauf: [BETRAG]."),
    ("Festpreis 8300", "8300 wäre okay. [BETRAG]?"),
    (TITLE, "Für die 126610LN: [BETRAG]."),
])
async def test_no_digit_drafts_are_written_anew_told_why_regardless_of_the_title(kept, title, written):
    box = Box()
    await opened(kept, box)
    negotiation = kept.get("3535834511")
    negotiation.title = title
    kept.save(negotiation)
    box.seller("Unter 9.500 € geht nichts.")
    claude = Claude(reads=[says(price=9500)], writes=[written, "Das ist mir zu viel. [BETRAG]?"])

    await negotiator(claude, kept).follow_up(box)

    assert box.said[-1].text == "Das ist mir zu viel. 8.050 €?"
    assert "no digit" in asked_to_write(claude)
    assert "not even one the seller wrote" in asked_to_write(claude)
    assert "Write no digit" in instructed(claude) and '"zwei Tage"' in instructed(claude)


@pytest.mark.parametrize("written, why", [
    ("Passt für Sie eine Überweisung?", '"Sie" says "Sie" to the seller, not "du"'),
    ("Wären\nSie mit [BETRAG] einverstanden?", '"Sie" says "Sie" to the seller, not "du"'),  # a line break ends no sentence
    ("Hallo, würden Ihnen [BETRAG] passen?", '"Ihnen" says "Sie" to the seller, not "du"'),
    ("Ok. Was wäre Ihr Preis?", '"Ihr" says "Sie" to the seller, not "du"'),
    ("Ihr Preis ist mir zu hoch, [BETRAG] passt für mich.", '"Ihr" says "Sie" to the seller, not "du"'),
    ("[BETRAG], das ergibt sich aus dem Vergleich mit aktuellen Angeboten.", '"Vergleich" points to other offers or the market'),
    ("Das liegt über dem, was ich bei ähnlichen Uhren sehe.", '"ähnlich" points to other offers or the market'),
    ("Der Marktpreis liegt eher bei [BETRAG].", '"Marktpreis" points to other offers or the market'.replace("Marktpreis", "Markt")),
    ("Die Preise sind gerade gefallen.", '"Preise" points to other offers or the market'),
    ("[BETRAG] wäre ok, bei anderen Angeboten zahle ich weniger.", '"anderen Angebot" points to other offers or the market'),
    ("[BETRAG] ergibt sich aus aktuellen Angeboten.", '"Angeboten" points to other offers or the market'),
    ("In den Inseraten wird weniger verlangt.", '"Inseraten" points to other offers or the market'),
    ("[BETRAG] ergibt sich aus den Preisen anderer Uhren.", '"Preisen" points to other offers or the market'),
    ("Ich habe ein anderes Inserat für [BETRAG] gesehen.", '"anderes Inserat" points to other offers or the market'),
    ("Wie angeboten, [BETRAG]. Dein Inserat ist ja noch online.", None),
    ("[BETRAG] wäre ok, bei den Angeboten anderer Verkäufer zahle ich weniger.", '"Angeboten" points to other offers or the market'),
    ("Angeboten hätte ich dir [BETRAG]. Passt das für dich?", None),  # first in its sentence: the buyer's own
    ("Angebote anderer Verkäufer liegen unter [BETRAG].", '"Angebote" points to other offers or the market'),
    ("[BETRAG] wäre ok, bei den\nAngeboten anderer Verkäufer zahle ich weniger.", '"Angeboten" points to other offers or the market'),
    ("Ich hatte dir etwas anderes angeboten, [BETRAG] wären für mich ok.", None),  # the verb
    ("Sie ist noch da? Passt dir eine Überweisung?", None),  # at a sentence's start, the watch
    ("Hallo, ist sie noch zu haben?", None),
    ("Mehr ist sie mir nicht wert, [BETRAG] ginge.", None),
    ("Privat, ich sammle Uhren.", '"Privat" says the buyer buys privately: he trades watches'),
    ("Ich kaufe als Privatperson.", '"Privat" says the buyer buys privately: he trades watches'),
    ("Ich handle mit Uhren.", None),
])
def test_the_buyer_says_du_points_to_no_other_offer_and_buys_as_a_trader(written, why):
    assert negotiation.unlike_the_buyer(written) == why


async def test_a_draft_saying_sie_or_pointing_to_other_offers_is_written_anew_told_why_and_each_time_goes_to_the_owner(kept):
    box = Box()
    await opened(kept, box)
    box.seller("Unter 9.500 € geht nichts.")
    claude = Claude(reads=[says(price=9500)], writes=["Wären [BETRAG] für Sie ok?", "Wären [BETRAG] für dich ok?"])

    await negotiator(claude, kept).follow_up(box)

    assert box.said[-1].text == "Wären 8.050 € für dich ok?"
    assert 'refused: "Sie" says "Sie" to the seller, not "du"' in asked_to_write(claude)

    box.seller("Na gut, 9.400 €.")
    each = ["Ähnliche Uhren gehen für [BETRAG] weg.", "Im Vergleich sind [BETRAG] fair.", "Passt Ihnen [BETRAG]?"]
    await negotiator(Claude(reads=[says(price=9400)], writes=each), kept).follow_up(box)

    gone = kept.get("3535834511")
    assert gone.status == "owner" and '"Ihnen" says "Sie" to the seller' in gone.notice  # the last refusal


async def test_an_answer_written_wrong_each_time_goes_to_the_owner_the_drafts_logged(kept, caplog):
    box = Box()
    await opened(kept, box)
    box.seller("Was ist Ihr bestes Angebot?")

    await negotiator(Claude(reads=[says()], writes=["Maximal 9.000 €.", "Bis neuntausend.", "Für 9k?"]), kept).follow_up(box)

    assert box.said[-1].text == "Was ist Ihr bestes Angebot?"
    assert kept.get("3535834511").status == "owner" and "amount decided alone" in kept.get("3535834511").notice
    assert [r.message.rsplit(": ", 1)[1] for r in caplog.records if "draft refused" in r.message] == [
        "Maximal 9.000 €.", "Bis neuntausend.", "Für 9k?"]


async def test_a_draft_refused_twice_has_a_third_try(kept):
    box = Box()
    await opened(kept, box)
    box.seller("Was ist dein bestes Angebot?")

    await negotiator(Claude(reads=[says()], writes=["Maximal 9.000 €.", "Bis neuntausend.", "Was wäre denn dein Preis?"]),
                     kept).follow_up(box)

    assert box.said[-1].text == "Was wäre denn dein Preis?" and kept.get("3535834511").status == "talking"


async def test_a_settling_message_each_time_leaving_a_term_unnamed_goes_to_the_owner_told_which(kept):
    box = Box()
    await opened(kept, box)
    box.seller("Ok, 7.550 passt. Überweisung und Kaufvertrag gehen klar.")
    unnamed = "Super, [BETRAG] passt! Schickst du mir noch ein Foto deines Ausweises?"

    await negotiator(Claude(reads=[says(accepts_offer=True, bank_transfer=True, contract=True)], writes=[unnamed] * 3),
                     kept).follow_up(box)

    gone = kept.get("3535834511")
    assert gone.status == "owner" and "the AI wrote no message naming insured shipping" in gone.notice


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
    box.seller("Unter 9.500 € geht nichts.")

    async def sent_but_answered_at_once(conversation_id, text):
        box.said.append(Said(True, " ".join(text.split("\n"))))
        box.seller("Und mit Versand?")
        raise RuntimeError("conversation c1 does not end with the message written")

    box.reply = sent_but_answered_at_once
    await negotiator(Claude(reads=[says(price=9500)], writes=["Wie wäre es\nmit [BETRAG]?"]), kept).follow_up(box)
    del box.reply
    await negotiator(Claude(reads=[says(price=9500, question="Und mit Versand?")],
                            writes=["Versichert, im Preis. Was ginge bei dir noch?"]), kept).follow_up(box)

    assert kept.get("3535834511").status == "talking"
    assert box.said[-1].text == "Versichert, im Preis. Was ginge bei dir noch?"  # it keeps 8.050 €, the seller holding
    assert kept.get("3535834511").offered == 8050


async def test_an_answer_that_did_not_reach_the_seller_is_sent_again_not_decided_again(kept):
    box = Box()
    await opened(kept, box)
    box.seller("Unter 9.500 € geht nichts.")
    box.reply = AsyncMock(side_effect=RuntimeError("the site did not answer"))
    await negotiator(Claude(reads=[says(price=9500)], writes=["Wie wäre es mit [BETRAG]?"]), kept).follow_up(box)
    del box.reply
    again = Claude()

    await negotiator(again, kept).follow_up(box)

    assert again.asked == [] and box.said[-1].text == "Wie wäre es mit 8.050 €?"


async def test_a_seller_who_wrote_after_an_answer_failed_is_read_and_the_answer_taken_back(kept):
    box = Box()
    await opened(kept, box)
    box.seller("Unter 9.500 € geht nichts, und nur bar.")
    box.reply = AsyncMock(side_effect=RuntimeError("the site did not answer"))
    await negotiator(Claude(reads=[says(price=9500, bank_transfer=False)], writes=["Wie wäre es mit [BETRAG] per Überweisung?"]),
                     kept).follow_up(box)
    box.seller("Keine Antwort? Dann eben 9.200 €, aber bar.")
    del box.reply
    claude = Claude(reads=[says(price=9200, bank_transfer=False)], writes=["Für [BETRAG] gern, aber nur per Überweisung."])

    await negotiator(claude, kept).follow_up(box)

    assert [s.text for s in box.said if s.outbound] == ["Ist die Uhr noch zu haben?", "Ich biete 7.550 €.",
                                                        "Für 8.050 € gern, aber nur per Überweisung."]
    now = kept.get("3535834511")
    assert (now.status, now.offered, now.terms.asked_again) == ("talking", 8050, [])  # the refusal waits for its turn


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
    "Super, [BETRAG]! Kannst du die Uhr versichert verschicken?",
    "Super, [BETRAG]! Würdest du sie mir versichert zuschicken? Dann ist sie am schnellsten bei mir.",
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
    await negotiator(Claude(reads=[says(price=12000)], writes=["Schade, da komme ich nicht mit. Melde dich gern."]),
                     kept).follow_up(box)
    assert kept.get("3535834511").status == "ended"
    quiet = Claude()
    await negotiator(quiet, kept).follow_up(box)
    assert quiet.asked == []  # its own farewell is the last word

    box.seller("Ok, dann machen wir 8.600 €.")
    claude = Claude(reads=[says(price=8600)], writes=["Prima, [BETRAG]! Passt dir Überweisung?"])
    talking = negotiator(claude, kept)
    assert [n.ad_id for n in talking.waiting()] == ["3535834511"]
    await talking.follow_up(box)

    assert box.said[-1].text == "Prima, 8.600 €! Passt dir Überweisung?"
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
    claude = Claude(reads=[says()], writes=["Ja, gern. Was wäre dein Preis?"])
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
    monitor.deals = Deals(tmp_path / "deals.sqlite3")
    return monitor


async def press(monitor, judged):
    monitor.agent = Agent(None, None, None, monitor.deals, logging.getLogger("test"),
                          on_requested_verdict=monitor._negotiate_by_hand)
    monitor.agent.judge = AsyncMock(return_value=(judged[0], None, judged[1]))
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


async def test_above_asking_automatic_negotiations_keep_the_price_read_from_the_ad(by_hand, kept):
    verdict = Verdict(True, "worth contacting", Decimal("10800"), Decimal("8600"), Decimal("7000"))
    agent = Agent(None, None, None, by_hand.deals, logging.getLogger("test"), by_hand._negotiate_if_asked)
    agent.judge = AsyncMock(return_value=(Decimal("8000"), None, verdict))
    watch = WatchData(title=TITLE, url="https://www.kleinanzeigen.de/s-anzeige/3535834511",
                      site_name="Kleinanzeigen", site_key="filter:42", price=Decimal("9900"))

    await agent.consider([watch])

    (asked,) = kept.with_status("pending")
    assert (asked.asking, asked.limit, asked.offered) == (8000, 8600, 7000)
    assert watch.price == Decimal("9900")  # reading the ad does not change the match's alert


async def test_above_asking_the_button_keeps_the_price_read_from_the_ad(by_hand, kept):
    await press(by_hand, (Decimal("8000"), Verdict(True, "worth contacting", Decimal("10800"), Decimal("8600"))))

    (asked,) = kept.with_status("pending")
    assert (asked.asking, asked.limit, asked.offered) == (8000, 8600, 7000)


async def test_the_button_says_why_the_agent_leaves_a_match_without_a_limit(by_hand, kept):
    await press(by_hand, (Decimal("9000"), Verdict(False, "red flags: signs of a replica")))

    assert kept.with_status("pending") == []
    by_hand._tell_owner.assert_awaited_once_with(
        "filter:43", "The agent leaves https://www.kleinanzeigen.de/s-anzeige/3519758108 alone: red flags: signs of a replica."
    )
