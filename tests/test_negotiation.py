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

    assert (answer.kind, answer.price, terms.price) == ("settle", 7550, 7550)
    assert list(terms.open()) == ["payment by bank transfer", "insured shipping, or else pickup",
                                  "the purchase contract", "a picture of the seller's ID card"]


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
    assert list(terms.open()) == ["payment by bank transfer"]


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
    talking = negotiator(Claude(writes=["Ich biete [BETRAG]."]), kept, notify)
    talking.ask_to_start(asked_for())
    with pytest.raises(asyncio.CancelledError):
        await negotiation.keep_talking(talking, "session.json", logging.getLogger("test"),
                                       now=lambda: datetime(2026, 10, 11, hour, 0, tzinfo=negotiation.GERMANY))


async def test_the_talk_loop_writes_by_day_with_the_owner_s_session_and_keeps_it_renewed(monkeypatch, kept):
    box, browser = Box(), Browser()

    await one_look(monkeypatch, kept, box, browser, hour=10)

    assert [s.text for s in box.said] == ["Ich biete 7.550 €."]
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
                                    "Super, [BETRAG]! Den Kaufvertrag schicke ich, dazu bräuchte ich ein Foto Ihres Ausweises."]),
                     kept).follow_up(box)

    assert box.said[-1].text.endswith("Foto Ihres Ausweises.")


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

    assert [s.text for s in box.said if s.outbound] == ["Ich biete 7.550 €.", "Für 7.850 € gern, aber nur per Überweisung."]
    now = kept.get("3535834511")
    assert (now.status, now.offered, now.terms.asked_again) == ("talking", 7850, ["bank transfer"])  # refused once


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
    "Super, [BETRAG]! Können Sie die Uhr versichert verschicken? Für den Vertrag bitte noch ein Foto vom Perso.",
    "Super, [BETRAG]! Abholung ginge auch. Den Kaufvertrag schicke ich, dazu bräuchte ich ein Foto Ihres Ausweises.",
])
async def test_a_settling_message_may_name_the_terms_as_people_do(kept, words):
    box = Box()
    await opened(kept, box)
    box.seller("Ok, 7.550 € passt, Überweisung geht klar.")
    claude = Claude(reads=[says(accepts_offer=True, bank_transfer=True)], writes=[words])

    await negotiator(claude, kept).follow_up(box)

    assert box.said[-1].text == words.replace("[BETRAG]", "7.550 €")
    task = json.loads(claude.requests[-1])["messages"][0]["content"][0]["text"]
    assert '("Versand")' in task and '("Kaufvertrag")' in task and '("Ausweis")' in task  # the AI is told the words


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
