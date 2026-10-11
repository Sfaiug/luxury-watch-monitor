"""The buying agent's negotiation: what it answers a seller by the owner's terms, and how it writes to them."""

import json
import logging
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx2
import pytest
from anthropic import AsyncAnthropic

from kleinanzeigen_messages import Unsent
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
        self.reads, self.writes, self.asked = list(reads), list(writes), []

    def answer(self, request):
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
    return Negotiator(claude, kept, notify or AsyncMock(), logging.getLogger("test"))


async def test_a_negotiation_asked_for_opens_once_with_the_opening_offer_written_in(kept):
    box, talking = Box(), negotiator(Claude(writes=["Hallo, ist die Uhr noch zu haben? Ich würde [BETRAG] bieten."]), kept)

    assert talking.ask_to_start(asked_for()) and kept.get("3535834511").status == "pending"
    assert not talking.ask_to_start(asked_for())
    await talking.start(box)
    await talking.start(box)

    assert [s.text for s in box.said] == ["Hallo, ist die Uhr noch zu haben? Ich würde 7.550 € bieten."]
    opened = kept.get("3535834511")
    assert (opened.status, opened.conversation, opened.sent) == ("talking", "c1", [box.said[0].text])


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
    talking = negotiator(Claude(writes=["Ich biete [BETRAG]."]), kept)
    talking.ask_to_start(asked_for())

    await talking.start(Box(contact_fails=True))

    gone = kept.get("3535834511")
    assert (gone.status, gone.sent) == ("owner", ["Ich biete 7.550 €."])
    assert "could not see its first message reach the seller" in gone.notice


async def test_a_first_message_that_never_left_is_sent_as_it_was_at_the_next_look_and_at_the_third_goes_to_the_owner(kept):
    claude = Claude(writes=["Ich biete [BETRAG]."])
    talking = negotiator(claude, kept)
    talking.ask_to_start(asked_for())
    refusing = Box(contact_fails=Unsent("the offer page did not load"))

    await talking.start(refusing)
    assert (kept.get("3535834511").status, kept.get("3535834511").notice) == ("pending", "")

    box = Box()
    await talking.start(box)
    assert [s.text for s in box.said] == ["Ich biete 7.550 €."] and claude.asked == ["write"]  # written once

    again = negotiator(Claude(writes=["Ich biete [BETRAG]."]), kept)
    gone = asked_for()
    gone.ad_id = "1"
    again.ask_to_start(gone)
    for _ in range(3):
        await again.start(refusing)
    assert kept.get("1").status == "owner" and "took no message" in kept.get("1").notice


async def opened(kept, box):
    talking = negotiator(Claude(writes=["Ich biete [BETRAG]."]), kept)
    talking.ask_to_start(asked_for())
    await talking.start(box)


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


async def test_an_answer_written_wrong_twice_goes_to_the_owner(kept):
    box = Box()
    await opened(kept, box)
    box.seller("Was ist Ihr bestes Angebot?")

    await negotiator(Claude(reads=[says()], writes=["Maximal 9.000 €.", "Bis neuntausend."]), kept).follow_up(box)

    assert box.said[-1].text == "Was ist Ihr bestes Angebot?"
    assert kept.get("3535834511").status == "owner" and kept.get("3535834511").notice


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
    await negotiator(Claude(reads=[says(price=8500, question="Und mit Versand?")], writes=["Versichert, im Preis: [BETRAG]."]),
                     kept).follow_up(box)

    assert kept.get("3535834511").status == "talking"
    assert box.said[-1].text == "Versichert, im Preis: 8.250 €."  # the next counter, the seller holding at 8.500 €


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


async def test_a_message_settling_the_rest_names_every_term_still_open(kept):
    box = Box()
    await opened(kept, box)
    box.seller("Ok, 7.550 € passt, Überweisung und Versand gehen klar.")

    # The ID card left out of the first message, as the real model once waived it
    await negotiator(Claude(reads=[says(accepts_offer=True, bank_transfer=True, delivery="shipping")],
                            writes=["Super, [BETRAG] per Überweisung! Den Kaufvertrag schicke ich.",
                                    "Super, [BETRAG]! Für den Kaufvertrag brauche ich noch ein Foto Ihres Ausweises."]),
                     kept).follow_up(box)

    assert box.said[-1].text == "Super, 7.550 €! Für den Kaufvertrag brauche ich noch ein Foto Ihres Ausweises."

