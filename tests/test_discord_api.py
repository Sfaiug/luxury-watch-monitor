"""The bot's one way to Discord, against a local server standing in for it."""

import json
from types import SimpleNamespace
from unittest.mock import patch

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from discord_api import DiscordApi


@pytest.fixture
async def discord():
    """(the caller, the requests the server got, the answers it will give in turn)."""
    got, answers = [], []

    async def answer(request):
        got.append(
            {
                "method": request.method,
                "path": request.path_qs,
                "authorization": request.headers.get("Authorization"),
                "user_agent": request.headers.get("User-Agent"),
                "body": await request.text(),
            }
        )
        status, body = answers.pop(0) if answers else (200, {"id": "1"})
        if isinstance(body, str):
            return web.Response(status=status, text=body)
        return web.json_response(body, status=status)

    app = web.Application()
    app.router.add_route("*", "/{path:.*}", answer)
    server = TestServer(app)
    await server.start_server()
    async with aiohttp.ClientSession() as session:
        config = SimpleNamespace(
            discord_bot_token="bot-token", discord_api_base_url=str(server.make_url("/api/v10/"))
        )
        yield DiscordApi(session, config), got, answers
    await server.close()


async def test_a_call_is_made_as_the_bot(discord):
    api, got, _ = discord

    status, answer = await api.call("POST", "/channels/5/messages", {"content": "hello"})

    assert (status, answer) == (200, {"id": "1"})
    (request,) = got
    assert (request["method"], request["path"]) == ("POST", "/api/v10/channels/5/messages")
    assert request["authorization"] == "Bot bot-token"
    assert request["user_agent"].startswith("DiscordBot (")
    assert json.loads(request["body"]) == {"content": "hello"}


async def test_a_question_is_asked_without_a_body(discord):
    api, got, _ = discord

    await api.call("GET", "/channels/5/messages", params={"limit": "2"})

    assert (got[0]["path"], got[0]["body"]) == ("/api/v10/channels/5/messages?limit=2", "")


async def test_told_to_slow_down_it_waits_as_long_as_discord_says_and_asks_once_more(discord):
    api, got, answers = discord
    answers += [(429, {"message": "You are being rate limited.", "retry_after": 0.25}), (201, {"id": "9"})]

    with patch("discord_api.asyncio.sleep") as waited:
        status, answer = await api.call("POST", "/channels/5/messages", {"content": "hello"})

    assert (status, answer) == (201, {"id": "9"})
    waited.assert_awaited_once_with(0.25)
    assert len(got) == 2


async def test_told_to_slow_down_twice_it_gives_that_answer(discord):
    api, got, answers = discord
    answers += [(429, {"retry_after": 0.01})] * 2

    with patch("discord_api.asyncio.sleep"):
        status, _ = await api.call("GET", "/channels/5")

    assert status == 429 and len(got) == 2


async def test_an_answer_that_is_no_json_is_given_as_its_text(discord):
    api, _, answers = discord
    answers.append((502, "Bad Gateway"))

    assert await api.call("GET", "/channels/5") == (502, {"message": "Bad Gateway"})
