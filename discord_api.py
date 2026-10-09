"""The bot's calls to Discord: its headers, its address and what it does when told to slow down."""

import asyncio
import json
from typing import Any, Optional, Tuple

import aiohttp


class DiscordApi:
    """Calls Discord as the bot named in `config` (its token and Discord's address)."""

    def __init__(self, session, config):
        self.session = session
        self.config = config

    async def call(
        self, method: str, path: str, body: Optional[dict] = None, params: Optional[dict] = None
    ) -> Tuple[int, Any]:
        """One call; (status, answer). Told to slow down, it waits as long as Discord says and asks once more."""
        request = {
            "headers": {
                "Authorization": f"Bot {self.config.discord_bot_token}",
                "User-Agent": "DiscordBot (https://atlas.hopcomp.com, 1.0)",
            },
            "timeout": aiohttp.ClientTimeout(total=15),
        }
        if body is not None:
            request["json"] = body
        if params:
            request["params"] = params
        url = self.config.discord_api_base_url.rstrip("/") + path

        for attempt in range(2):
            async with getattr(self.session, method.lower())(url, **request) as response:
                text = await response.text()
                try:
                    answer = json.loads(text)
                except (TypeError, ValueError):
                    answer = {"message": str(text)[:500]}
                if response.status != 429 or attempt:
                    return response.status, answer
                wait = answer.get("retry_after") if isinstance(answer, dict) else None
                wait = float(wait or response.headers.get("Retry-After") or 1)
            await asyncio.sleep(wait)
