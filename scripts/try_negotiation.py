#!/usr/bin/env python3
"""The owner tries the agent as a seller: it negotiates for a pretend watch in a DM with the bot, through the
production code (the AI, `negotiation.move`, the terms, what the owner is told); only the Kleinanzeigen message box
is that DM, and what it keeps lasts as long as the run.

On the server, in the checkout: venv/bin/python3 scripts/try_negotiation.py
"""

import asyncio
import logging
import random
import sys
import tempfile
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

import aiohttp  # noqa: E402
from anthropic import AsyncAnthropic  # noqa: E402

from agent import opening  # noqa: E402
from config import APP_CONFIG  # noqa: E402
from discord_api import DiscordApi  # noqa: E402
from kleinanzeigen_messages import Conversation, Message, Unsent  # noqa: E402
from negotiation import Negotiation, Negotiations, Negotiator, euros  # noqa: E402

AD = "try"
# The pretend watch, at what one was worth on 12 Oct 2026
TITLE = "Rolex Submariner 124060, 2022, Box und Papiere"
ASKING, LIMIT = 9900, 8366
A_WHILE = (60, 180)  # the seconds an answer waits here, drawn between these; the agent itself waits longer
LOOK_EVERY = 15  # seconds between looks at the DM
LASTS = timedelta(hours=3)  # the longest a try runs
NOTE = "Try"  # how the bot's own notes in the DM start, which are no part of the conversation


class DirectMessages:
    """The message box the agent uses, as a DM with the owner: the bot's messages are the buyer's, the owner's the
    seller's."""

    PAGE = 100  # the most messages Discord gives at once

    def __init__(self, api: DiscordApi, channel: str):
        self.api, self.channel = api, channel

    async def post(self, content: str) -> dict:
        status, answer = await self.api.call("POST", f"/channels/{self.channel}/messages", {"content": content})
        if 400 <= status < 500:  # refused: nothing was sent
            raise Unsent(f"Discord answered {status}: {answer}")
        if status not in (200, 201):  # it may have been sent all the same
            raise RuntimeError(f"Discord answered {status}: {answer}")
        return answer

    async def contact(self, ad_id: str, text: str) -> str:
        try:
            start = await self.post(
                f"**{NOTE}.** You are the seller now. Your ad: *{TITLE}*, asking {euros(ASKING)}. The agent pays at "
                f"most {euros(LIMIT)}. Answer it here as a seller would, in German; a picture you send counts as "
                "the ID card. The buyer's messages follow.")
        except Exception as e:
            raise Unsent(str(e)) from e
        await self.post(text)
        return start["id"]

    async def conversation(self, conversation_id: str) -> Conversation:
        # Discord gives the messages after one a page at a time
        answer, after = [], conversation_id
        while True:
            status, page = await self.api.call(
                "GET", f"/channels/{self.channel}/messages", params={"after": after, "limit": self.PAGE})
            if status != 200:
                raise RuntimeError(f"Discord answered {status}: {page}")
            answer += page
            if len(page) < self.PAGE:
                break
            after = max(page, key=lambda m: int(m["id"]))["id"]
        said = sorted((m for m in answer if not (m["author"].get("bot") and m["content"].startswith(NOTE))),
                      key=lambda m: int(m["id"]))
        return Conversation(conversation_id, AD, "the owner", [
            Message(bool(m["author"].get("bot")), m["content"], len(m.get("attachments") or []), m["timestamp"])
            for m in said])

    async def reply(self, conversation_id: str, text: str):
        await self.post(text)


async def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logger = logging.getLogger("try_negotiation")
    owner = APP_CONFIG.muv_allowed_requester_ids.split(",")[0].strip()
    with tempfile.TemporaryDirectory() as kept:
        negotiations = Negotiations(str(Path(kept) / "deals.sqlite3"))
        async with aiohttp.ClientSession() as session:
            api = DiscordApi(session, APP_CONFIG)
            status, dm = await api.call("POST", "/users/@me/channels", {"recipient_id": owner})
            if status not in (200, 201):
                raise RuntimeError(f"Discord answered {status}: {dm}")
            box = DirectMessages(api, dm["id"])

            async def notify(channel, text):
                await box.post(f"{NOTE}, what you would be told: {text}")

            negotiator = Negotiator(AsyncAnthropic(), negotiations, notify, logger,
                                    a_while=lambda: timedelta(seconds=random.uniform(*A_WHILE)))
            negotiator.ask_to_start(Negotiation(
                ad_id=AD, channel="this DM", title=TITLE, address="this DM", limit=LIMIT,
                offered=int(opening(Decimal(ASKING), Decimal(LIMIT)))))
            until, shown = datetime.now() + LASTS, None
            while datetime.now() < until:
                await negotiator.start(box)
                await negotiator.follow_up(box)
                await negotiator.tell_owner()
                n = negotiations.get(AD)
                if (n.status, n.offered, n.terms) != shown:
                    shown = (n.status, n.offered, n.terms)
                    logger.info(f"{n.status} at {euros(n.offered)}, {n.terms} {n.why}")
                # An ended one goes on: the agent answers a seller who writes again
                if n.status in ("agreed", "owner") and not n.notice:
                    break
                await asyncio.sleep(LOOK_EVERY)
        negotiations.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
