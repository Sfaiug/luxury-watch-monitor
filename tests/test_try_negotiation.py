"""The DM the owner plays the seller in, as the agent's message box."""

import asyncio

import pytest

from kleinanzeigen_messages import Unsent
from scripts import try_negotiation as trying


class Discord:
    def __init__(self, messages=(), status=200):
        self.messages, self.status, self.posted = list(messages), status, []

    async def call(self, method, path, body=None, params=None):
        if method == "POST":
            self.posted.append(body["content"])
            return self.status, {"id": str(len(self.posted))}
        return self.status, self.messages


def test_a_first_message_follows_a_note_the_conversation_starts_after():
    discord = Discord()
    started = asyncio.run(trying.DirectMessages(discord, "dm").contact("try", "Hallo, ist die Uhr noch zu haben?"))
    assert started == "1"
    assert discord.posted[0].startswith(f"**{trying.NOTE}.**")
    assert discord.posted[1] == "Hallo, ist die Uhr noch zu haben?"


def test_a_first_message_discord_refuses_is_unsent():
    with pytest.raises(Unsent):
        asyncio.run(trying.DirectMessages(Discord(status=403), "dm").contact("try", "Hallo"))


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
