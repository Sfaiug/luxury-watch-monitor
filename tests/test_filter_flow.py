"""The "New filter" conversation, against a stand-in for Discord that records every call."""

import asyncio
import logging
from dataclasses import replace

import pytest

import filter_flow
from discord_interactions import DiscordInteractionServer
from filter_flow import FilterFlow
from filters import STORES, Filter, FilterStore

GUILD, BOT, MEMBER_ID, CATEGORY = "900", "800", "42", "700"


class Discord:
    """Answers like Discord and remembers what it was asked."""

    def __init__(self):
        self.calls = []
        self.channels = [{"id": "1", "name": "worldoftime", "parent_id": CATEGORY}]
        self.messages = {}
        self.refuse_channels = None

    async def call(self, method, path, body=None):
        self.calls.append((method, path, body))
        if method == "GET" and path == f"/guilds/{GUILD}/channels":
            return 200, list(self.channels)
        if method == "GET" and path.endswith("/messages?limit=1"):
            return 200, self.messages.get(path.split("/")[2], [])[-1:]
        if method == "GET" and path.startswith("/channels/"):
            channel = next((c for c in self.channels if c["id"] == path.split("/")[2]), None)
            return (200, {**channel, "guild_id": GUILD}) if channel else (404, {})
        if method == "POST" and path == f"/guilds/{GUILD}/channels":
            if self.refuse_channels:
                return 403, {"message": self.refuse_channels}
            channel = {**body, "id": str(100 + len(self.channels))}
            self.channels.append(channel)
            return 201, channel
        if method == "POST" and path.endswith("/messages"):
            channel = next(c for c in self.channels if c["id"] == path.split("/")[2])
            if not self.bot_may_post(channel):
                return 403, {"message": "Missing Permissions"}
            self.messages.setdefault(channel["id"], []).append(body)
            return 200, body
        return 200, {}

    @staticmethod
    def bot_may_post(channel):
        """What a channel denies everyone it denies the bot too, unless it allows the bot by name."""
        see_and_send = filter_flow.VIEW_CHANNEL | filter_flow.SEND_MESSAGES
        allowed = see_and_send
        for overwrite in channel.get("permission_overwrites", []):
            if overwrite["id"] == GUILD:
                allowed &= ~int(overwrite.get("deny", 0))
        for overwrite in channel.get("permission_overwrites", []):
            if overwrite["id"] == BOT:
                allowed |= int(overwrite.get("allow", 0))
        return allowed & see_and_send == see_and_send

    def said(self, method, path_end):
        return [body for m, path, body in self.calls if m == method and path.endswith(path_end)]


@pytest.fixture
def discord():
    return Discord()


@pytest.fixture
def scanned():
    return []


@pytest.fixture
def flow(tmp_path, discord, scanned, monkeypatch):
    monkeypatch.setenv("WORLDOFTIME_CHANNEL_ID", "1")

    async def scan(new):
        scanned.append(new)

    return FilterFlow(
        FilterStore(tmp_path / "filters.json"), discord, logging.getLogger("test"), scan
    )


def press(custom_id, **data):
    return {
        "type": 3,
        "guild_id": GUILD,
        "application_id": BOT,
        "token": "tok",
        "channel": {"id": "5", "parent_id": CATEGORY},
        "member": {"user": {"id": MEMBER_ID}},
        "data": {"custom_id": custom_id, **data},
    }


def form(store, seller, words, min_price="", max_price=""):
    fields = {"words": words, "min_price": min_price, "max_price": max_price}
    return {
        **press(f"filter:form:{store}:{seller}"),
        "type": 5,
        "data": {
            "custom_id": f"filter:form:{store}:{seller}",
            "components": [
                {"type": 1, "components": [{"type": 4, "custom_id": name, "value": value}]}
                for name, value in fields.items()
            ],
        },
    }


def choices(reply):
    return [
        (button["label"], button["custom_id"])
        for row in reply["data"]["components"]
        for button in row["components"]
    ]


async def finish(flow):
    await asyncio.gather(*flow._tasks)


async def test_from_the_button_to_a_channel_only_the_member_sees(flow, discord, scanned):
    # One marketplace: the first question is who sells
    asked = flow.handle(press("filter:new"))
    assert asked["data"]["flags"] == 64  # only the member sees the conversation
    assert choices(asked) == [
        ("Private sellers", "filter:seller:kleinanzeigen:private"),
        ("Dealers", "filter:seller:kleinanzeigen:dealer"),
        ("Both", "filter:seller:kleinanzeigen:any"),
    ]

    asked = flow.handle(press("filter:seller:kleinanzeigen:private"))
    assert asked["type"] == 9 and asked["data"]["custom_id"] == "filter:form:kleinanzeigen:private"
    assert [row["components"][0]["custom_id"] for row in asked["data"]["components"]] == [
        "words",
        "min_price",
        "max_price",
    ]

    reply = flow.handle(form("kleinanzeigen", "private", "Rolex Submariner", "5.000 €", "9000"))
    assert reply == {"type": 5, "data": {"flags": 64}}
    await finish(flow)

    made = Filter("101", MEMBER_ID, "kleinanzeigen", "private", "Rolex Submariner", 5000, 9000)
    assert flow.store.all() == [made]
    assert scanned == [made]  # scanned at once

    (channel,) = discord.said("POST", f"/guilds/{GUILD}/channels")
    assert channel["name"] == "Rolex Submariner"
    assert channel["topic"] == f"Kleinanzeigen · Private sellers · €5.000 to €9.000 · {made.search_url}"
    assert channel["parent_id"] == CATEGORY  # beside the button's channel
    everyone, member, bot = channel["permission_overwrites"]
    assert (everyone["id"], everyone["deny"]) == (GUILD, str(1 << 10))  # nobody else sees it
    assert member["id"] == MEMBER_ID and int(member["allow"]) & (1 << 10)
    assert int(member["allow"]) & (1 << 4)  # the member may delete it
    assert bot["id"] == BOT

    assert discord.said("PATCH", "/webhooks/800/tok/messages/@original") == [
        {"content": "Your filter is running: <#101>"}
    ]


async def test_with_two_marketplaces_the_first_question_is_where(flow, monkeypatch):
    monkeypatch.setitem(STORES, "ebay", replace(STORES["kleinanzeigen"], name="eBay"))

    asked = flow.handle(press("filter:new"))

    assert asked["data"]["content"] == "Where should I look?"
    assert choices(asked) == [
        ("Kleinanzeigen", "filter:store:kleinanzeigen"),
        ("eBay", "filter:store:ebay"),
    ]
    asked = flow.handle(press("filter:store:ebay"))
    assert asked["type"] == 7  # the same message moves on to the next question
    assert choices(asked)[0] == ("Private sellers", "filter:seller:ebay:private")


async def test_prices_are_optional_and_put_in_order(flow, discord):
    flow.handle(form("kleinanzeigen", "any", "Omega Speedmaster", "9000", "3000"))
    flow.handle(form("kleinanzeigen", "dealer", "Cartier Tank"))
    await finish(flow)

    speedmaster, tank = sorted(flow.store.all(), key=lambda f: f.words, reverse=True)
    assert (speedmaster.min_price, speedmaster.max_price) == (3000, 9000)
    assert (tank.min_price, tank.max_price) == (None, None)
    assert filter_flow.describe(tank) == "Kleinanzeigen · Dealers"


async def test_the_member_is_told_when_the_channel_cannot_be_made(flow, discord, scanned):
    discord.refuse_channels = "Missing Permissions"

    flow.handle(form("kleinanzeigen", "any", "Rolex Submariner"))
    await finish(flow)

    assert flow.store.all() == [] and scanned == []
    assert discord.said("PATCH", "/messages/@original") == [
        {"content": "I could not make your filter: Missing Permissions"}
    ]


async def test_the_member_is_told_when_the_filter_cannot_be_kept(flow, discord, scanned, monkeypatch):
    def full(new):
        raise OSError("No space left on device")

    monkeypatch.setattr(flow.store, "add", full)

    flow.handle(form("kleinanzeigen", "any", "Rolex Submariner"))
    await finish(flow)

    assert scanned == []
    assert discord.said("PATCH", "/messages/@original") == [
        {"content": "I could not make your filter: No space left on device"}
    ]


async def test_the_button_is_put_beside_the_shops_once(flow, discord):
    await flow.tend()
    await flow.tend()

    (channel,) = discord.said("POST", f"/guilds/{GUILD}/channels")
    assert channel == {"name": "new-filter", "type": 0, "parent_id": CATEGORY}
    (message,) = discord.messages[discord.channels[-1]["id"]]
    assert choices({"data": message}) == [("New filter", "filter:new")]


async def test_the_button_is_tried_again_until_the_bot_may_make_channels(flow, discord):
    discord.refuse_channels = "Missing Permissions"
    await flow.tend()
    assert len(discord.channels) == 1

    discord.refuse_channels = None
    await flow.tend()

    assert discord.channels[-1]["name"] == "new-filter"


async def test_deleting_the_channel_ends_the_filter(flow, discord):
    flow.handle(form("kleinanzeigen", "any", "Rolex Submariner"))
    await finish(flow)
    await flow.tend()
    assert len(flow.store.all()) == 1

    discord.channels = [c for c in discord.channels if c.get("name") != "Rolex Submariner"]
    await flow.tend()

    assert flow.store.all() == []


async def test_the_interaction_endpoint_hands_filter_presses_to_the_flow(flow):
    server = DiscordInteractionServer(None, None, logging.getLogger("test"), flow)

    asked = await server.handle_payload(press("filter:new"))

    assert asked["data"]["content"] == "Who is selling?"
