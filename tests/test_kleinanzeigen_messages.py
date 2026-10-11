"""The owner's Kleinanzeigen messages, through a stand-in for a page of the site."""

import copy

import pytest

from kleinanzeigen_messages import Messages, NotSent, Unsent

USER = 4242


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
                "attachments": [{"title": "photo.jpg"}] * pictures,
                "messageId": f"m{n}",
                "unichatMessage": {"authorId": "1", "payload": {"type": "chat/text-message", "content": {"text": text}}},
            }
            for n, (boundness, text, pictures) in enumerate(messages)
        ],
    }


class Site:
    """A page of Kleinanzeigen: answers the message API as the gateway does, and has an offer page's contact form."""

    def __init__(self, conversations=(), listed_pages=None, shows_what_is_sent=True):
        self.conversations = {c["id"]: c for c in conversations}
        self.listed_pages = listed_pages or [[{"id": c["id"], "adId": c["adId"], "role": c["role"]} for c in conversations]]
        self.shows_what_is_sent = shows_what_is_sent
        self.calls, self.visited, self.typed, self.clicked = [], [], {}, []

    def _sent(self, conversation_id, text):
        if self.shows_what_is_sent:
            self.conversations[conversation_id]["messages"] += conversation(("OUTBOUND", text, 0))["messages"]

    async def evaluate(self, script, args=None):
        if args is None:
            return USER
        method, path, body = args
        self.calls.append((method, path, body))
        base = f"/messagebox/api/users/{USER}/conversations"
        if method == "GET" and path.startswith(base + "?"):
            page = int(path.split("page=")[1].split("&")[0])
            links = {"next": {"href": "…"}} if page + 1 < len(self.listed_pages) else {}
            return {"status": 200, "data": {"conversations": self.listed_pages[page], "_links": links}}
        conversation_id = path[len(base) + 1:].split("?")[0]
        if conversation_id not in self.conversations:
            return {"status": 404, "data": None}
        if method == "POST":
            self._sent(conversation_id, body["message"])
            return {"status": 201, "data": None}
        return {"status": 200, "data": copy.deepcopy(self.conversations[conversation_id])}

    async def goto(self, url, **options):
        self.visited.append(url)

    async def fill(self, selector, text):
        self.typed[selector] = text

    async def click(self, selector):
        self.clicked.append(selector)
        started = conversation(ad_id=self.visited[-1].rsplit("/", 1)[1])
        self.conversations[started["id"]] = started
        self.listed_pages[-1].append({"id": started["id"], "adId": started["adId"], "role": "Buyer"})
        self._sent(started["id"], self.typed["#viewad-contact-message"])

    async def wait_for_selector(self, selector, **options):
        assert selector == ".j-viewad-contact-success" and self.clicked


async def test_a_conversation_reads_as_it_was_written():
    site = Site([conversation(("OUTBOUND", "Hallo, wäre bei 9.000 € dabei.", 0), ("INBOUND", "Gern, hier mein Ausweis.", 1))])

    read = await Messages(site).conversation("abc:1:xyz")

    assert (read.id, read.ad_id, read.seller) == ("abc:1:xyz", "3535834511", "Tim")
    assert [(m.outbound, m.text, m.attachments) for m in read.messages] == [
        (True, "Hallo, wäre bei 9.000 € dabei.", 0),
        (False, "Gern, hier mein Ausweis.", 1),  # whole, though its short text is cut
    ]


async def test_a_reply_counts_as_sent_once_its_conversation_shows_it():
    site = Site([conversation(("INBOUND", "Was bieten Sie?", 0))])

    await Messages(site).reply("abc:1:xyz", "9.200 € wären möglich.")

    assert ("POST", f"/messagebox/api/users/{USER}/conversations/abc:1:xyz", {"message": "9.200 € wären möglich."}) in site.calls

    with pytest.raises(NotSent):
        await Messages(Site([conversation(("INBOUND", "Was bieten Sie?", 0))], shows_what_is_sent=False)).reply(
            "abc:1:xyz", "9.200 € wären möglich."
        )


async def test_a_message_said_before_counts_only_once_it_shows_again():
    asked_before = Site([conversation(("OUTBOUND", "Ist die Uhr noch da?", 0), ("INBOUND", "Ja", 0))],
                        shows_what_is_sent=False)

    with pytest.raises(NotSent):
        await Messages(asked_before).reply("abc:1:xyz", "Ist die Uhr noch da?")


async def test_a_first_message_goes_through_the_offer_s_contact_form_and_its_conversation_is_found():
    # The account sells too: a conversation about another ad as its seller, on the first page of two
    selling = {"id": "own:1", "adId": "111", "role": "Seller"}
    site = Site(listed_pages=[[selling], []])

    started = await Messages(site).contact("3535834511", "Hallo, ist die Uhr noch da?")

    assert site.visited == ["https://www.kleinanzeigen.de/s-anzeige/3535834511"]
    assert site.typed == {"#viewad-contact-message": "Hallo, ist die Uhr noch da?"}
    assert started == "abc:1:xyz"


async def test_the_conversation_found_is_the_one_the_account_buys_in():
    selling_the_same_ad = conversation(ad_id="3535834511")
    selling_the_same_ad.update(id="own:2", role="Seller")

    assert await Messages(Site([selling_the_same_ad])).bought("3535834511") is None


async def test_an_answer_with_an_error_is_no_answer():
    with pytest.raises(RuntimeError, match="404"):
        await Messages(Site()).conversation("gone")


async def test_a_contact_form_that_could_not_be_filled_sent_nothing():
    site = Site(listed_pages=[[]])

    async def gone(url, **options):
        raise RuntimeError("the offer page did not load")

    site.goto = gone
    with pytest.raises(Unsent):
        await Messages(site).contact("3535834511", "Hallo, ist die Uhr noch da?")
    assert site.clicked == []

