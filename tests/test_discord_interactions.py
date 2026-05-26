"""Tests for Discord interaction handling."""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from action_store import ActionStore
from discord_interactions import (
    EPHEMERAL_FLAG,
    RESPONSE_CHANNEL_MESSAGE,
    RESPONSE_PONG,
    DiscordInteractionServer,
    verify_discord_signature,
)
from models import WatchData


class FakeMUVService:
    def __init__(self):
        self.handled = []
        self.published = []
        self.published_links = []

    async def handle_action(self, action_id):
        self.handled.append(action_id)

    async def publish_offer(self, action_id, payload):
        self.published.append((action_id, payload))
        return SimpleNamespace(status="completed", error=None)

    async def publish_offer_link(self, url):
        self.published_links.append(url)
        return SimpleNamespace(status="completed", error=None)


class FakeOfferRequest:
    def __init__(self, payload, *, secret=None):
        self._payload = payload
        self.headers = {"X-MUV-Action-Secret": secret} if secret else {}
        self.query = {}

    async def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_ping_returns_pong(mock_logger, temp_dir):
    store = ActionStore(str(temp_dir / "actions.sqlite3"))
    try:
        server = DiscordInteractionServer(store, FakeMUVService(), mock_logger)

        response = await server.handle_payload({"type": 1})

        assert response == {"type": RESPONSE_PONG}
    finally:
        await server.stop()
        store.close()


@pytest.mark.asyncio
async def test_component_queues_muv_action(mock_logger, temp_dir):
    store = ActionStore(str(temp_dir / "actions.sqlite3"))
    fake_muv = FakeMUVService()
    try:
        watch = WatchData(
            title="Rolex Daytona",
            url="https://example.com/daytona",
            site_name="Example",
            site_key="example",
        )
        action_id = store.save_watch(watch)
        server = DiscordInteractionServer(store, fake_muv, mock_logger)

        response = await server.handle_payload(
            {
                "id": "interaction-1",
                "type": 3,
                "data": {"custom_id": f"muv:{action_id}"},
                "member": {"user": {"id": "123", "username": "tester"}},
            }
        )

        assert response["type"] == RESPONSE_CHANNEL_MESSAGE
        assert response["data"]["flags"] == EPHEMERAL_FLAG
        assert "queued" in response["data"]["content"]

        record = store.get(action_id)
        assert record.status == "queued"
        assert record.requested_by == "123"
    finally:
        await server.stop()
        store.close()


@pytest.mark.asyncio
async def test_duplicate_component_click_reports_existing_status(mock_logger, temp_dir):
    store = ActionStore(str(temp_dir / "actions.sqlite3"))
    try:
        action_id = store.save_watch(
            WatchData(
                title="Omega Speedmaster",
                url="https://example.com/speedmaster",
                site_name="Example",
                site_key="example",
            )
        )
        store.queue_action(action_id, "123", "tester", "interaction-1")

        server = DiscordInteractionServer(store, FakeMUVService(), mock_logger)
        response = await server.handle_payload(
            {
                "id": "interaction-2",
                "type": 3,
                "data": {"custom_id": f"muv:{action_id}"},
            }
        )

        assert "already `queued`" in response["data"]["content"]
    finally:
        await server.stop()
        store.close()


def test_verify_discord_signature_round_trip():
    signing = pytest.importorskip("nacl.signing")
    signing_key = signing.SigningKey.generate()
    verify_key = signing_key.verify_key

    timestamp = "1779800000"
    body = json.dumps({"type": 1}).encode("utf-8")
    signature = signing_key.sign(timestamp.encode("utf-8") + body).signature.hex()

    assert (
        verify_discord_signature(verify_key.encode().hex(), signature, timestamp, body)
        is True
    )
    assert (
        verify_discord_signature(verify_key.encode().hex(), "00" * 64, timestamp, body)
        is False
    )


@pytest.mark.asyncio
async def test_muv_offer_webhook_publishes_received_price(mock_logger, temp_dir):
    store = ActionStore(str(temp_dir / "actions.sqlite3"))
    fake_muv = FakeMUVService()
    try:
        server = DiscordInteractionServer(store, fake_muv, mock_logger)
        request = FakeOfferRequest(
            {"action_id": "abc123", "price": "24000", "currency": "EUR"},
            secret="shared-secret",
        )

        with patch("discord_interactions.APP_CONFIG") as mock_config:
            mock_config.action_token_secret = "shared-secret"
            response = await server.handle_muv_offer(request)

        assert response.status == 200
        assert fake_muv.published == [
            ("abc123", {"action_id": "abc123", "price": "24000", "currency": "EUR"})
        ]
    finally:
        await server.stop()
        store.close()


@pytest.mark.asyncio
async def test_muv_offer_webhook_accepts_muv_url_without_action_id(
    mock_logger, temp_dir
):
    store = ActionStore(str(temp_dir / "actions.sqlite3"))
    fake_muv = FakeMUVService()
    try:
        server = DiscordInteractionServer(store, fake_muv, mock_logger)
        url = "https://www.meineuhrverkaufen.de/Sell/request-1?mt=token"
        request = FakeOfferRequest({"muv_url": url}, secret="shared-secret")

        with patch("discord_interactions.APP_CONFIG") as mock_config:
            mock_config.action_token_secret = "shared-secret"
            response = await server.handle_muv_offer(request)

        assert response.status == 200
        assert fake_muv.published_links == [url]
    finally:
        await server.stop()
        store.close()
