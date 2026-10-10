"""The "New filter" conversation in Discord: from the button to the filter's own channel."""

import asyncio
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

from discord_api import DiscordApi
from discord_interactions import (
    EPHEMERAL_FLAG,
    RESPONSE_CHANNEL_MESSAGE,
    RESPONSE_DEFERRED_CHANNEL_MESSAGE,
    RESPONSE_MODAL,
    RESPONSE_UPDATE_MESSAGE,
)
from filters import STORES, Filter, FilterStore
from utils import parse_price

SELLERS = {"private": "Private sellers", "dealer": "Dealers", "any": "Both"}
CONDITIONS = {"new": "New", "very_good": "Very good", "good": "Good", "okay": "Okay"}
WIDGET_CHANNEL = "new-filter"
WIDGET_TEXT = (
    "**Filters**\n"
    "Press the button and answer the questions. Every new match then arrives in a "
    "channel only you can see. To stop a filter, delete its channel."
)

# Discord: permission bits, and whom a channel's permission is for
VIEW_CHANNEL, SEND_MESSAGES, EMBED_LINKS, MANAGE_CHANNELS = 1 << 10, 1 << 11, 1 << 14, 1 << 4
ROLE, MEMBER = 0, 1


def _buttons(*buttons: Tuple[str, str]) -> list:
    return [
        {
            "type": 1,
            "components": [
                {"type": 2, "style": 1, "label": label, "custom_id": custom_id}
                for label, custom_id in buttons
            ],
        }
    ]


def describe(new: Filter) -> str:
    """The filter in a line: "Kleinanzeigen · Private sellers · New, Very good · 5000 to 9000 €"."""
    parts = [STORES[new.store].name, SELLERS[new.seller]]
    if new.conditions:
        parts.append(", ".join(CONDITIONS[condition] for condition in new.conditions))
    if new.min_price and new.max_price:
        parts.append(f"{new.min_price} to {new.max_price} €")
    elif new.min_price:
        parts.append(f"from {new.min_price} €")
    elif new.max_price:
        parts.append(f"up to {new.max_price} €")
    return " · ".join(parts)


class FilterFlow:
    """Asks a member where to look, who sells, in which condition and for what, then makes the filter and its channel."""

    def __init__(
        self,
        store: FilterStore,
        discord: DiscordApi,
        logger,
        on_created: Callable[[Filter], Awaitable[None]],
        beside: str,
    ):
        """`beside`: a channel the shops' alerts go to; the button's channel joins its category."""
        self.store = store
        self.discord = discord
        self.logger = logger
        self.on_created = on_created
        self.beside = beside
        self._widget_ready = False
        self._tasks = set()

    # -- the conversation: each answer carries the earlier ones in its custom_id

    def handle(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """The reply to a press or a sent form whose custom_id starts with "filter:"; None for a step that is none of the flow's."""
        data = payload.get("data") or {}
        _, step, *answers = data.get("custom_id", "").split(":")

        if step == "new":
            if len(STORES) > 1:
                return self._ask(
                    RESPONSE_CHANNEL_MESSAGE,
                    "Where should I look?",
                    _buttons(*((store.name, f"filter:store:{key}") for key, store in STORES.items())),
                )
            return self._ask_seller(RESPONSE_CHANNEL_MESSAGE, next(iter(STORES)))
        if step == "store":
            return self._ask_seller(RESPONSE_UPDATE_MESSAGE, *answers)
        if step == "seller":
            return self._ask_condition(*answers)
        if step == "condition":
            # The "Any condition" button names none
            return self._form(*answers[:2], *data.get("values", []))
        if step == "form":
            return self._create(payload, *answers)
        return None

    def _ask(self, kind: int, question: str, components: list) -> Dict[str, Any]:
        return {
            "type": kind,
            "data": {"content": question, "flags": EPHEMERAL_FLAG, "components": components},
        }

    def _ask_seller(self, kind: int, store: str) -> Dict[str, Any]:
        return self._ask(
            kind,
            "Who is selling?",
            _buttons(*((label, f"filter:seller:{store}:{seller}") for seller, label in SELLERS.items())),
        )

    def _ask_condition(self, store: str, seller: str) -> Dict[str, Any]:
        step = f"filter:condition:{store}:{seller}"
        several = {
            "type": 3,
            "custom_id": step,
            "placeholder": "Choose one or more",
            "min_values": 1,
            "max_values": len(CONDITIONS),
            "options": [{"label": label, "value": key} for key, label in CONDITIONS.items()],
        }
        return self._ask(
            RESPONSE_UPDATE_MESSAGE,
            "In which condition?",
            [{"type": 1, "components": [several]}, *_buttons(("Any condition", f"{step}:any"))],
        )

    def _form(self, store: str, seller: str, *conditions: str) -> Dict[str, Any]:
        def line(custom_id, label, required=False, placeholder=""):
            field = {
                "type": 4,
                "custom_id": custom_id,
                "label": label,
                "style": 1,
                "required": required,
                "max_length": 80,
                "placeholder": placeholder,
            }
            return {"type": 1, "components": [field]}

        return {
            "type": RESPONSE_MODAL,
            "data": {
                "custom_id": ":".join(("filter", "form", store, seller, *conditions)),
                "title": "New filter",
                "components": [
                    line("words", "What are you looking for?", True, "Rolex Submariner 16610"),
                    line("min_price", "Lowest price in € (optional)", placeholder="5000"),
                    line("max_price", "Highest price in € (optional)", placeholder="9000"),
                ],
            },
        }

    def _create(
        self, payload: Dict[str, Any], store: str, seller: str, *conditions: str
    ) -> Dict[str, Any]:
        answers = {
            field["custom_id"]: field["value"].strip()
            for row in payload["data"]["components"]
            for field in row["components"]
        }
        # Whole euros, read as every price is: "5.000 €", "5,000" and "5000" are 5000
        lowest, highest = (
            int(price) if (price := parse_price(answers[bound])) else None
            for bound in ("min_price", "max_price")
        )
        if lowest and highest and lowest > highest:
            lowest, highest = highest, lowest

        task = asyncio.create_task(
            self._open_channel(
                payload,
                dict(
                    user_id=payload["member"]["user"]["id"],
                    store=store,
                    seller=seller,
                    words=answers["words"],
                    min_price=lowest,
                    max_price=highest,
                    conditions=list(conditions),
                ),
            )
        )
        self._tasks.add(task)
        task.add_done_callback(self._made)
        # Making the channel takes longer than Discord waits for a reply
        return {"type": RESPONSE_DEFERRED_CHANNEL_MESSAGE, "data": {"flags": EPHEMERAL_FLAG}}

    async def _open_channel(self, payload: Dict[str, Any], answers: Dict[str, Any]):
        """Make the member's channel beside the button's, keep the filter, and say where it is."""
        guild_id, bot_id = payload["guild_id"], payload["application_id"]
        new = None
        try:
            pending = Filter(channel_id="", **answers)
            status, channel = await self.discord.call(
                "POST",
                f"/guilds/{guild_id}/channels",
                {
                    "name": pending.words,
                    "type": 0,
                    "topic": f"{describe(pending)} · {pending.search_url}",
                    "parent_id": (payload.get("channel") or {}).get("parent_id"),
                    "permission_overwrites": [
                        {"id": guild_id, "type": ROLE, "deny": str(VIEW_CHANNEL)},
                        {
                            "id": pending.user_id,
                            "type": MEMBER,
                            "allow": str(VIEW_CHANNEL | MANAGE_CHANNELS),
                        },
                        {
                            "id": bot_id,
                            "type": MEMBER,
                            "allow": str(VIEW_CHANNEL | SEND_MESSAGES | EMBED_LINKS),
                        },
                    ],
                },
            )
            if status != 201:
                raise RuntimeError(channel.get("message", status))
            new = Filter(channel_id=channel["id"], **answers)
            self.store.add(new)
            said = f"Your filter is running: <#{new.channel_id}>"
        except Exception as e:
            self.logger.error(f"Could not make a filter: {e!r}")
            new, said = None, f"I could not make your filter: {e}"

        await self.discord.call(
            "PATCH",
            f"/webhooks/{bot_id}/{payload['token']}/messages/@original",
            {"content": said},
        )
        if new:
            await self.on_created(new)

    def _made(self, task: asyncio.Task):
        self._tasks.discard(task)
        if not task.cancelled() and task.exception():
            self.logger.error(f"Error after making a filter: {task.exception()!r}")

    # -- upkeep, once per monitoring cycle

    async def tend(self):
        """Put the button where the shops' channels are, and forget filters whose channel is gone."""
        try:
            if not self._widget_ready:
                self._widget_ready = await self._place_widget()
            for kept in self.store.all():
                status, _ = await self.discord.call("GET", f"/channels/{kept.channel_id}")
                if status == 404:
                    self.store.remove(kept.channel_id)
        except Exception as e:
            self.logger.error(f"Error tending the filters: {e}")

    async def _place_widget(self) -> bool:
        status, beside = await self.discord.call("GET", f"/channels/{self.beside}")
        if status != 200:
            return False
        guild_id = beside["guild_id"]
        status, channels = await self.discord.call("GET", f"/guilds/{guild_id}/channels")
        if status != 200:
            return False
        channel = next(
            (
                c
                for c in channels
                if c["name"] == WIDGET_CHANNEL and c.get("parent_id") == beside.get("parent_id")
            ),
            None,
        )
        if not channel:
            status, channel = await self.discord.call(
                "POST",
                f"/guilds/{guild_id}/channels",
                # With no permissions of its own it takes its category's, as the
                # shops' channels do: who reads those reads this, and the bot posts
                {"name": WIDGET_CHANNEL, "type": 0, "parent_id": beside.get("parent_id")},
            )
            if status != 201:
                self.logger.warning(f"Could not make #{WIDGET_CHANNEL}: {status} {channel}")
                return False

        messages = f"/channels/{channel['id']}/messages"
        status, posted = await self.discord.call("GET", messages + "?limit=1")
        if status == 200 and not posted:
            status, _ = await self.discord.call(
                "POST",
                messages,
                {"content": WIDGET_TEXT, "components": _buttons(("New filter", "filter:new"))},
            )
        return status == 200
