"""The owner's Kleinanzeigen messages, through a stand-in for a page of the site."""

import asyncio
import html
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from playwright.async_api import TimeoutError

from kleinanzeigen_messages import CannotWrite, LoggedOut, Messages, NotSent, Unsent

USER = 4242


def response(path, status=200, data=None):
    return {"status": status, "path": path, "text": json.dumps(data) if data is not None else ""}


def conversation(*messages, ad_id="3535834511"):
    """A conversation as the message API answers it (its shape on 11 Oct 2026), messages as (boundness, text, pictures)."""
    return {
        "id": "abc:1:xyz",
        "role": "Buyer",
        "buyerName": "Owner",
        "sellerName": "Tim",
        "adId": ad_id,
        "messages": [
            {
                "textShort": text[:20],
                "boundness": boundness,
                "type": "MESSAGE",
                "receivedDate": f"2026-10-11T09:0{n}:00.000+0200",
                "attachments": [
                    {"title": "photo.jpg", "gatewayUrl": f"https://gateway.kleinanzeigen.de/pictures/{n}-{p}"}
                    for p in range(pictures)
                ],
                "messageId": f"m{n}",
                "unichatMessage": {"authorId": "1", "payload": {"type": "chat/text-message", "content": {"text": text}}},
            }
            for n, (boundness, text, pictures) in enumerate(messages)
        ],
    }


class Site:
    """The message box's page, and the session its offer tabs share."""

    def __init__(self, conversations=(), listed_pages=None, shows_what_is_sent=True):
        self.conversations = {c["id"]: c for c in conversations}
        self.listed_pages = listed_pages or [[{"id": c["id"], "adId": c["adId"], "role": c["role"]} for c in conversations]]
        self.shows_what_is_sent = shows_what_is_sent
        self.calls, self.tabs = [], []
        self.context = SimpleNamespace(new_page=self.new_page)

    async def new_page(self):
        tab = OfferTab(self)
        self.tabs.append(tab)
        return tab

    def _sent(self, conversation_id, text):
        if self.shows_what_is_sent:
            self.conversations[conversation_id]["messages"] += conversation(("OUTBOUND", text, 0))["messages"]

    async def evaluate(self, script, args=None):
        if args is None:
            return response("/messagebox-api/view", data={"user": {"id": USER}})
        method, path, body = args
        self.calls.append((method, path, body))
        base = f"/messagebox/api/users/{USER}/conversations"
        if method == "GET" and path.startswith(base + "?"):
            page = int(path.split("page=")[1].split("&")[0])
            links = {"next": {"href": "…"}} if page + 1 < len(self.listed_pages) else {}
            return response(path, data={"conversations": self.listed_pages[page], "_links": links})
        conversation_id = path[len(base) + 1:].split("?")[0]
        if conversation_id not in self.conversations:
            return response(path, 404)
        if method == "POST":
            self._sent(conversation_id, body["message"])
            return response(path, 201)
        return response(path, data=self.conversations[conversation_id])


class OfferTab:
    """An offer's contact form, sending to the same account's message box."""

    def __init__(self, site):
        self.site = site
        self.visited, self.typed, self.clicked = [], {}, []
        self.closed = False
        self.pressed = None

    async def add_init_script(self, script):
        pass

    async def goto(self, url, **options):
        self.visited.append(url)
        return SimpleNamespace(status=200, text=AsyncMock(return_value="<html>Contact form</html>"))

    async def fill(self, selector, text):
        self.typed[selector] = text

    async def evaluate(self, script):
        if script == "window.__watchMonitorContactPressed = false":
            self.pressed = False
        else:
            assert script == "window.__watchMonitorContactPressed === false"
            return self.pressed is False

    async def click(self, selector):
        self.pressed = True
        self.clicked.append(selector)
        started = conversation(ad_id=self.visited[-1].rsplit("/", 1)[1])
        self.site.conversations.setdefault(started["id"], started)
        self.site.listed_pages[-1].append({"id": started["id"], "adId": started["adId"], "role": "Buyer"})
        self.site._sent(started["id"], self.typed["#viewad-contact-message"])

    async def wait_for_selector(self, selector, **options):
        assert selector == ".j-viewad-contact-success" and self.clicked

    async def close(self):
        self.closed = True


async def test_a_conversation_reads_as_it_was_written():
    site = Site([conversation(("OUTBOUND", "Hallo, wäre bei 9.000 € dabei.", 0), ("INBOUND", "Gern, hier mein Ausweis.", 1))])
    on_success = Mock()

    read = await Messages(site, on_success=on_success).conversation("abc:1:xyz")

    assert on_success.call_count == 2
    assert (read.id, read.ad_id, read.seller, read.buyer) == ("abc:1:xyz", "3535834511", "Tim", "Owner")
    assert [(m.outbound, m.text, m.attachments) for m in read.messages] == [
        (True, "Hallo, wäre bei 9.000 € dabei.", []),
        (False, "Gern, hier mein Ausweis.", ["https://gateway.kleinanzeigen.de/pictures/1-0"]),  # whole text
    ]


async def test_id_card_seen_picture_is_read_only_on_demand_through_the_session():
    site = Site([conversation(("INBOUND", "Hier.", 2))])
    on_success = Mock()
    box = Messages(site, on_success=on_success)
    read = await box.conversation("abc:1:xyz")
    on_success.reset_mock()
    picture = {"media_type": "image/jpeg", "data": "cGljdHVyZQ=="}
    site.evaluate = AsyncMock(return_value=picture)

    assert len(read.messages[0].attachments) == 2
    assert await box.picture(read.messages[0].attachments[0]) == picture
    on_success.assert_called_once_with()

    script, url = site.evaluate.await_args.args
    assert url == "https://gateway.kleinanzeigen.de/pictures/0-0"
    assert "Authorization: token" in script and "/m-access-token.json" in script
    assert "cache: 'no-store'" in script
    assert vars(box) == {"_page": site, "_user": USER, "_on_success": on_success}


@pytest.mark.parametrize("answer", [
    RuntimeError("private attachment URL and contents"),
    {"media_type": "text/html", "data": "not a picture"},
    {"media_type": "image/png", "data": ""},
])
async def test_id_card_seen_unreadable_picture_does_not_leak_into_errors(answer):
    page = SimpleNamespace(evaluate=AsyncMock(**({"side_effect": answer} if isinstance(answer, Exception)
                                               else {"return_value": answer})))
    with pytest.raises(RuntimeError, match="^Could not read a chat picture$"):
        await Messages(page).picture("private attachment URL")


async def test_a_reply_counts_as_sent_once_its_conversation_shows_it():
    site = Site([conversation(("INBOUND", "Was bieten Sie?", 0))])

    await Messages(site).reply("abc:1:xyz", "9.200 € wären möglich.")

    assert ("POST", f"/messagebox/api/users/{USER}/conversations/abc:1:xyz", {"message": "9.200 € wären möglich."}) in site.calls

    with pytest.raises(NotSent):
        await Messages(Site([conversation(("INBOUND", "Was bieten Sie?", 0))], shows_what_is_sent=False)).reply(
            "abc:1:xyz", "9.200 € wären möglich."
        )


@pytest.mark.parametrize("sending", ["reply", "contact"])
async def test_a_message_shown_after_a_while_counts_as_sent(mocker, sending):
    text = "Danke! Der Kaufvertrag kommt gleich."
    site = Site([conversation(("OUTBOUND", text, 0), ("INBOUND", "Ja, gern.", 0))], shows_what_is_sent=False)
    elapsed = 0

    async def show_after_a_while(seconds):
        nonlocal elapsed
        elapsed += seconds
        if elapsed >= 3 and not site.shows_what_is_sent:
            site.shows_what_is_sent = True
            site._sent("abc:1:xyz", text)

    mocker.patch("kleinanzeigen_messages.asyncio.sleep", side_effect=show_after_a_while)
    box = Messages(site)

    if sending == "reply":
        await box.reply("abc:1:xyz", text)
        assert sum(method == "POST" for method, _, _ in site.calls) == 1
    else:
        assert await box.contact("3535834511", text) == "abc:1:xyz"
        assert len(site.tabs[0].clicked) == 1 and site.tabs[0].closed

    assert 3 <= elapsed <= 5


class JoiningLines(Site):
    """The site showing a message with its lines broken otherwise than written."""

    def _sent(self, conversation_id, text):
        super()._sent(conversation_id, " ".join(text.split("\n")))


async def test_a_message_counts_as_sent_however_the_site_breaks_its_lines():
    await Messages(JoiningLines([conversation(("INBOUND", "Was bieten Sie?", 0))])).reply("abc:1:xyz", "Wie wäre es\nmit 8.000 €?")
    assert await Messages(JoiningLines()).contact("3535834511", "Hallo,\nist die Uhr noch da?") == "abc:1:xyz"


@pytest.mark.parametrize("sending", ["reply", "contact"])
async def test_earlier_messages_a_message_counts_as_sent_with_the_sites_html_escapes(sending):
    class Escaping(Site):
        def _sent(self, conversation_id, text):
            super()._sent(conversation_id, html.escape(text).replace(" ", "&nbsp;"))

    box = Messages(Escaping([conversation(("INBOUND", "Ja, noch da.", 0))]))
    text = 'Hallo, ist die Uhr & das "Band" noch da?'
    if sending == "reply":
        await box.reply("abc:1:xyz", text)
    else:
        assert await box.contact("3535834511", text) == "abc:1:xyz"


async def test_a_message_said_before_counts_only_once_it_shows_again():
    asked_before = Site([conversation(("OUTBOUND", "Ist die Uhr noch da?", 0), ("INBOUND", "Ja", 0))],
                        shows_what_is_sent=False)

    with pytest.raises(NotSent):
        await Messages(asked_before).reply("abc:1:xyz", "Ist die Uhr noch da?")


async def test_a_first_message_uses_its_own_tab_and_its_conversation_is_found():
    # The account sells too: a conversation about another ad as its seller, on the first page of two
    selling = {"id": "own:1", "adId": "111", "role": "Seller"}
    site = Site(listed_pages=[[selling], []])

    started = await Messages(site).contact("3535834511", "Hallo, ist die Uhr noch da?")

    assert len(site.tabs) == 1
    form = site.tabs[0]
    assert form.visited == ["https://www.kleinanzeigen.de/s-anzeige/3535834511"]
    assert form.typed == {"#viewad-contact-message": "Hallo, ist die Uhr noch da?"}
    assert form.closed
    assert started == "abc:1:xyz"


async def test_the_conversation_found_is_the_one_the_account_buys_in():
    selling_the_same_ad = conversation(ad_id="3535834511")
    selling_the_same_ad.update(id="own:2", role="Seller")

    assert await Messages(Site([selling_the_same_ad])).bought("3535834511") is None


async def test_an_answer_with_an_error_is_no_answer():
    with pytest.raises(RuntimeError, match="404"):
        await Messages(Site()).conversation("gone")


@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize("status, text, error", [
    (400, '{"message": "conversation deleted"}', CannotWrite),
    (403, '{"message": "seller blocked you"}', CannotWrite),
    (403, "seller blocked you", CannotWrite),
    (404, "", CannotWrite),
    (409, '{"message": "conversation closed"}', CannotWrite),
    (401, "<html>Log in</html>", LoggedOut),
    (429, '{"message": "Too many requests"}', RuntimeError),
    (500, '{"message": "Internal error"}', RuntimeError),
    (502, "<html>Bad gateway</html>", RuntimeError),
    (503, "<html>Unavailable</html>", RuntimeError),
    (200, "<html>Try again later</html>", RuntimeError),
    (403, "<html>Try again later</html>", RuntimeError),
])
async def test_cannot_write_keeps_a_refusal_separate_from_an_outage_and_a_401(method, status, text, error):
    path = f"/messagebox/api/users/{USER}/conversations/abc:1:xyz"
    page = SimpleNamespace(evaluate=AsyncMock(return_value={"status": status, "path": path, "text": text}))
    on_success = Mock()

    with pytest.raises(error) as raised:
        await Messages(page, on_success=on_success)._call(method, path, {"message": "Hallo"} if method == "POST" else None)

    on_success.assert_not_called()
    assert type(raised.value) is error
    assert str(status) in str(raised.value) and path in str(raised.value) and text in str(raised.value)


@pytest.mark.parametrize("source", ["/messagebox-api/view", "/m-access-token.json", "conversations"])
@pytest.mark.parametrize("status, error", [(401, LoggedOut), (403, RuntimeError), (429, RuntimeError), (503, RuntimeError)])
async def test_cannot_write_a_first_contact_does_not_blame_its_form_for_api_failures(source, status, error):
    site, before_send = Site(), Mock()
    box = Messages(site)
    if source != "/messagebox-api/view":
        await box._conversations()
    path = f"/messagebox/api/users/{USER}/conversations?page=0&size=100" if source == "conversations" else source
    answer = response(path, status, {"message": "refused"})
    if source == "/m-access-token.json":
        answer["error"] = "no access token"
    site.evaluate = AsyncMock(return_value=answer)
    expected = CannotWrite if source == "conversations" and status == 403 else error

    with pytest.raises(expected) as raised:
        await box.contact("3535834511", "Ist die Uhr noch da?", before_send=before_send)

    assert type(raised.value) is expected
    before_send.assert_not_called()
    assert not site.tabs


@pytest.mark.parametrize("status, error", [
    (401, LoggedOut), (403, RuntimeError), (404, RuntimeError),
    (429, RuntimeError), (500, RuntimeError), (503, RuntimeError),
])
async def test_cannot_write_a_first_contact_does_not_blame_its_form_for_page_failures(status, error):
    site, before_send = Site(), Mock()
    body = "<html>Service or login error</html>"
    answer = SimpleNamespace(status=status, text=AsyncMock(return_value=body))
    with patch.object(OfferTab, "goto", return_value=answer), \
            patch.object(OfferTab, "fill", side_effect=TimeoutError("no contact form")) as fill:
        with pytest.raises(error) as raised:
            await Messages(site).contact("3535834511", "Ist die Uhr noch da?", before_send=before_send)

    assert type(raised.value) is error
    assert str(status) in str(raised.value) and body in str(raised.value)
    fill.assert_not_awaited()
    before_send.assert_not_called()
    assert site.tabs[0].closed and not site.tabs[0].clicked


async def test_cannot_write_a_missing_access_token_is_an_outage():
    page = SimpleNamespace(evaluate=AsyncMock(return_value={
        **response("/m-access-token.json", 200), "error": "no access token",
    }))
    with pytest.raises(RuntimeError) as raised:
        await Messages(page)._call("GET", f"/messagebox/api/users/{USER}/conversations")
    assert type(raised.value) is RuntimeError


async def test_cannot_write_a_401_reading_a_picture_ends_the_login_without_leaking_the_picture():
    page = SimpleNamespace(evaluate=AsyncMock(return_value=response("chat picture", 401, "private contents")))
    with pytest.raises(LoggedOut, match="^Kleinanzeigen answered a chat picture request with 401$"):
        await Messages(page).picture("private attachment URL")


@pytest.mark.parametrize("failure", ["goto", "fill", "click"])
async def test_a_contact_form_in_its_own_tab_that_never_sent_can_be_tried_again(failure):
    site, before_send = Site(), Mock()
    box = Messages(site)
    text = "Hallo, ist die Uhr noch da?"
    with patch.object(OfferTab, failure, side_effect=TimeoutError("page failed or button covered")):
        with pytest.raises(Unsent):
            await box.contact("3535834511", text, before_send=before_send)

    assert site.tabs[0].closed and site.tabs[0].clicked == []
    assert await box.bought("3535834511") is None
    assert before_send.call_count == (1 if failure == "click" else 0)

    assert await box.contact("3535834511", text) == "abc:1:xyz"
    assert len(site.tabs) == 2 and site.tabs[1].closed
    assert [m.text for m in (await box.conversation("abc:1:xyz")).messages] == [text]


async def test_an_unresponsive_contact_form_marker_is_a_service_failure(monkeypatch):
    site, before_send = Site(), Mock()

    async def hangs(*args):
        await asyncio.Event().wait()

    monkeypatch.setattr("kleinanzeigen_messages.CALL_LIMIT", 0.01)
    monkeypatch.setattr(OfferTab, "evaluate", hangs)

    with pytest.raises(RuntimeError, match="did not respond"):
        await asyncio.wait_for(
            Messages(site).contact("3535834511", "Ist die Uhr noch da?", before_send=before_send), 0.2,
        )

    before_send.assert_not_called()
    assert site.tabs[0].closed and not site.tabs[0].clicked


@pytest.mark.parametrize("inspection", ["pressed", "navigated", "crashed", "unresponsive"])
async def test_a_click_in_its_own_tab_that_times_out_after_submission_is_not_unsent(inspection):
    site, before_send = Site(), Mock()
    click, evaluate = OfferTab.click, OfferTab.evaluate

    async def slow_click(form, selector):
        await click(form, selector)
        if inspection == "navigated":
            form.pressed = None  # a navigation loses the marker, not the submission
        raise TimeoutError("the click handler is still running after submission")

    async def inspect(form, script):
        if script == "window.__watchMonitorContactPressed === false":
            if inspection == "crashed":
                raise RuntimeError("the page crashed")
            if inspection == "unresponsive":
                await asyncio.Event().wait()
        return await evaluate(form, script)

    with patch.object(OfferTab, "click", slow_click), patch.object(OfferTab, "evaluate", inspect):
        with pytest.raises(TimeoutError):
            await Messages(site).contact("3535834511", "Hallo, ist die Uhr noch da?", before_send=before_send)

    before_send.assert_called_once_with(0)
    assert site.tabs[0].closed and len(site.tabs[0].clicked) == 1
    assert len((await Messages(site).conversation("abc:1:xyz")).messages) == 1


@pytest.mark.parametrize("failure", [TimeoutError("success notice did not appear"), asyncio.CancelledError()])
async def test_a_failure_after_clicking_in_its_own_tab_is_not_unsent(mocker, failure):
    site, before_send = Site(), Mock()
    mocker.patch.object(OfferTab, "wait_for_selector", side_effect=failure)

    with pytest.raises(type(failure)):
        await Messages(site).contact("3535834511", "Hallo, ist die Uhr noch da?", before_send=before_send)

    before_send.assert_called_once_with(0)
    assert site.tabs[0].closed and len(site.tabs[0].clicked) == 1
    assert len((await Messages(site).conversation("abc:1:xyz")).messages) == 1


async def test_a_message_from_its_own_tab_counts_only_once_its_conversation_shows_it():
    text, before_send = "Hallo, ist die Uhr noch da?", Mock()
    site = Site([conversation(("OUTBOUND", text, 0))], shows_what_is_sent=False)

    with pytest.raises(NotSent):
        await Messages(site).contact("3535834511", text, before_send=before_send)

    before_send.assert_called_once_with(1)
    assert site.tabs[0].closed
