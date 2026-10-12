"""The DM the owner plays the seller in, as the agent's message box."""

import asyncio

import pytest

from kleinanzeigen_messages import Unsent
from scripts import try_negotiation as trying


class Discord:
    def __init__(self, messages=(), refuses=0, loses=0):
        self.messages, self.refuses, self.loses, self.posted = list(messages), refuses, loses, []

    async def call(self, method, path, body=None, params=None):
        if method == "POST":
            self.posted.append(body["content"])
            if len(self.posted) == self.refuses:
                return 403, {"message": "refused"}
            if len(self.posted) == self.loses:
                raise TimeoutError("sent, its answer lost")
            return 200, {"id": str(len(self.posted))}
        # The oldest after the one named, as many as asked for at most, the newest first
        after = sorted((m for m in self.messages if int(m["id"]) > int(params["after"])), key=lambda m: int(m["id"]))
        return 200, after[:params["limit"]][::-1]


def test_a_first_message_follows_a_note_the_conversation_starts_after():
    discord = Discord()
    started = asyncio.run(trying.DirectMessages(discord, "dm").contact("try", "Hallo, ist die Uhr noch zu haben?"))
    assert started == "1"
    assert discord.posted[0].startswith(f"**{trying.NOTE}.**")
    assert discord.posted[1] == "Hallo, ist die Uhr noch zu haben?"


@pytest.mark.parametrize("refused", [1, 2], ids=["the note", "the message"])
def test_a_first_message_discord_refuses_is_unsent(refused):
    with pytest.raises(Unsent):
        asyncio.run(trying.DirectMessages(Discord(refuses=refused), "dm").contact("try", "Hallo"))


def test_a_first_message_whose_answer_is_lost_is_not_unsent():
    # It may have reached the seller: it goes to the owner, not out again
    with pytest.raises(TimeoutError):
        asyncio.run(trying.DirectMessages(Discord(loses=2), "dm").contact("try", "Hallo"))


def test_the_conversation_is_what_the_bot_and_the_owner_wrote_in_order_without_the_notes():
    discord = Discord([
        {"id": "12", "author": {"id": "owner"}, "content": "Ja, noch da.", "attachments": [], "timestamp": "t2"},
        {"id": "11", "author": {"id": "bot", "bot": True}, "content": "Hallo, ist die Uhr noch zu haben?",
         "timestamp": "t1"},
        {"id": "13", "author": {"id": "bot", "bot": True}, "content": f"{trying.NOTE}, what you would be told: …",
         "timestamp": "t3"},
        {"id": "14", "author": {"id": "owner"}, "content": "", "attachments": [{"id": "a"}], "timestamp": "t4"},
    ])
    talk = asyncio.run(trying.DirectMessages(discord, "dm").conversation("10"))
    assert [(m.outbound, m.text, m.attachments) for m in talk.messages] == [
        (True, "Hallo, ist die Uhr noch zu haben?", 0), (False, "Ja, noch da.", 0), (False, "", 1)]


def test_the_conversation_is_read_past_the_page_discord_gives():
    discord = Discord([{"id": str(n), "author": {"id": "owner"}, "content": str(n), "timestamp": "t"}
                       for n in range(11, 11 + trying.DirectMessages.PAGE + 1)])
    talk = asyncio.run(trying.DirectMessages(discord, "dm").conversation("10"))
    assert [m.text for m in talk.messages] == [str(n) for n in range(11, 11 + trying.DirectMessages.PAGE + 1)]
