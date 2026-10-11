"""The buying agent's negotiation: what it answers a seller by the owner's terms, and how it talks to them."""

import json
import logging
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx2
import pytest
from anthropic import AsyncAnthropic

from negotiation import Move, Negotiation, Negotiations, Negotiator, SellerSays, Terms, amounts, move

LIMIT, OPENING = 8600, 7550


def says(**said):
    stated = dict(price=None, accepts_offer=False, bank_transfer=None, delivery=None, contract=None, id_card=None,
                  ended=False, red_flags=[], question=None)
    stated.update(said)
    return SellerSays(**stated)


def test_an_offer_the_seller_accepts_is_the_price_and_the_rest_is_settled_next():
    terms = Terms()

    answer = move(LIMIT, OPENING, terms, says(accepts_offer=True), pictures=False)

    assert (answer.kind, answer.price, terms.price) == ("settle", 7550, 7550)
    assert terms.open() == ["payment by bank transfer", "insured shipping, or else pickup", "the purchase contract",
                            "a picture of the seller's ID card"]


def test_a_seller_asking_a_little_more_is_met_at_their_price():
    answer = move(LIMIT, OPENING, Terms(), says(price=7700), False)
    assert (answer.kind, answer.price) == ("settle", 7700)
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


@pytest.mark.parametrize("refusing", [dict(bank_transfer=False), dict(contract=False), dict(id_card=False)])
def test_a_seller_refusing_one_of_the_owner_s_terms_is_asked_once_more_then_bid_farewell(refusing):
    terms = Terms()

    first = move(LIMIT, OPENING, terms, says(price=7600, **refusing), False)
    assert (first.kind, first.price, len(first.refused)) == ("settle", 7600, 1)  # the price talk goes on beside it

    assert move(LIMIT, OPENING, terms, says(**refusing), False).kind == "farewell"


def test_a_term_the_seller_agreed_and_then_refuses_is_open_again():
    terms = Terms(price=OPENING, bank_transfer=True, delivery="shipping", contract=True, id_card=True)

    assert move(LIMIT, OPENING, terms, says(bank_transfer=False), False).kind == "settle"
    assert terms.open() == ["payment by bank transfer"]


def test_a_red_flag_or_a_sold_watch_ends_it_without_a_word():
    assert move(LIMIT, OPENING, Terms(), says(red_flags=["payment_or_contact_outside_kleinanzeigen"]), False).kind == "end"
    assert move(LIMIT, OPENING, Terms(), says(ended=True), False).kind == "end"


def test_all_is_agreed_once_the_id_card_is_shown_not_only_promised():
    terms = Terms(price=OPENING, bank_transfer=True, delivery="shipping", contract=True)

    assert move(LIMIT, OPENING, terms, says(id_card=True), pictures=False).kind == "settle"
    assert move(LIMIT, OPENING, terms, says(id_card=True), pictures=True) == Move("done", OPENING, "all agreed")


def test_the_amounts_a_message_names():
    assert amounts("Wäre bei 9.200 € dabei, oder 9200€, 9.200,- Euro, € 9200. Baujahr 2017, 41 mm.") == {9200}


@dataclass
class Said:
    outbound: bool
    text: str
    attachments: int = 0


class Box:
    """The owner's message box, with one seller in it."""

    def __init__(self):
        self.said = []

    async def contact(self, ad_id, text):
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
        self.reads, self.writes, self.asked = list(reads), list(writes), []

    def answer(self, request):
        asked = json.loads(request.content)
        writing = "message" in asked["output_config"]["format"]["schema"]["properties"]
        self.asked.append("write" if writing else "read")
        text = json.dumps({"message": self.writes.pop(0)}) if writing else self.reads.pop(0).model_dump_json()
        return httpx2.Response(200, json={"id": "m", "type": "message", "role": "assistant", "model": "m", "stop_reason": "end_turn",
                                          "usage": {"input_tokens": 1, "output_tokens": 1}, "content": [{"type": "text", "text": text}]})


def negotiation():
    return Negotiation(ad_id="3535834511", channel="filter:42", title="Rolex Submariner 116610LN",
                       address="https://www.kleinanzeigen.de/s-anzeige/3535834511", limit=LIMIT, offered=OPENING)


@pytest.fixture
def kept(tmp_path):
    return Negotiations(tmp_path / "deals.sqlite3")


def negotiator(claude, kept, notify=None):
    return Negotiator(claude, kept, notify or AsyncMock(), logging.getLogger("test"))


async def opened(kept, box, first="Ich biete 7.550 €."):
    talking = negotiator(Claude(writes=[first]), kept)
    talking.ask_to_start(negotiation())
    await talking.start(box)


async def test_a_negotiation_asked_for_opens_once_with_the_opening_offer(kept):
    box = Box()
    claude = Claude(writes=["Hallo, ist die Uhr noch da? Ich würde 7.550 € bieten."])
    talking = negotiator(claude, kept)

    assert talking.ask_to_start(negotiation()) and kept.get("3535834511").status == "pending"
    assert not talking.ask_to_start(negotiation())
    await talking.start(box)
    await talking.start(box)

    assert [s.text for s in box.said] == ["Hallo, ist die Uhr noch da? Ich würde 7.550 € bieten."]
    assert (kept.get("3535834511").conversation, kept.get("3535834511").status) == ("c1", "talking")


async def test_the_seller_s_counter_is_answered_with_the_agent_s_and_nothing_new_asks_nothing(kept):
    box = Box()
    await opened(kept, box)
    quiet = Claude()
    await negotiator(quiet, kept).follow_up(box)
    assert quiet.asked == []

    box.seller("Unter 8.500 € geht nichts.")
    claude = Claude(reads=[says(price=8500)], writes=["Wie wäre es mit 8.000 €?"])
    await negotiator(claude, kept).follow_up(box)

    assert box.said[-1].text == "Wie wäre es mit 8.000 €?"
    assert (kept.get("3535834511").offered, kept.get("3535834511").handled) == (8000, 3)


async def test_the_owner_hears_once_all_is_agreed(kept):
    box, notify = Box(), AsyncMock()
    await opened(kept, box)
    box.seller("Ok, 7.550 € passt. Überweisung, Versand und Kaufvertrag sind ok.")
    await negotiator(Claude(reads=[says(accepts_offer=True, bank_transfer=True, delivery="shipping", contract=True)],
                            writes=["Super! Schicken Sie mir noch ein Foto Ihres Ausweises für den Kaufvertrag?"]),
                     kept, notify).follow_up(box)
    notify.assert_not_awaited()

    box.seller("Hier mein Ausweis.", pictures=1)
    await negotiator(Claude(reads=[says(id_card=True)], writes=["Danke! Der Kaufvertrag kommt gleich, dann überweise ich die 7.550 €."]),
                     kept, notify).follow_up(box)

    assert kept.get("3535834511").status == "agreed"
    notify.assert_awaited_once()
    channel, text = notify.await_args.args
    assert channel == "filter:42" and "7.550 €" in text and "shipping" in text and "Kaufvertrag" in text


async def test_a_message_naming_another_amount_is_written_again_and_twice_hands_it_to_the_owner(kept):
    box, notify = Box(), AsyncMock()
    await opened(kept, box)
    box.seller("Was ist Ihr bestes Angebot?")

    await negotiator(Claude(reads=[says()], writes=["Maximal 9.000 €.", "Ich bleibe bei 7.550 €."]), kept).follow_up(box)
    assert box.said[-1].text == "Ich bleibe bei 7.550 €."

    box.seller("Und mehr?")
    await negotiator(Claude(reads=[says()], writes=["Bis 8.600 € ginge.", "Bis 8.600 €."]), kept, notify).follow_up(box)

    assert box.said[-1].text == "Und mehr?"
    assert kept.get("3535834511").status == "owner"
    notify.assert_awaited_once()


async def test_once_the_owner_writes_in_the_conversation_the_agent_stays_out(kept):
    box = Box()
    await opened(kept, box)
    box.seller("8.000?")
    box.said.append(Said(True, "Passt, mache ich selbst."))
    claude = Claude()

    await negotiator(claude, kept).follow_up(box)

    assert claude.asked == [] and kept.get("3535834511").status == "owner"
