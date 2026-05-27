"""End-to-end tests for the Discord button to MUV result path."""

import asyncio
import base64
import json
from decimal import Decimal
from urllib.parse import quote

import aiohttp
import pytest
from aiohttp import web

from action_store import ActionStore
from config import APP_CONFIG, SiteConfig
from discord_interactions import DiscordInteractionServer
from models import WatchData
from muv_service import MUVActionService
from notifications import NotificationManager


async def _start_site(app):
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return runner, f"http://127.0.0.1:{port}"


def _signed_headers(signing_key, body: bytes) -> dict:
    timestamp = "1779800000"
    signed_message = timestamp.encode("utf-8") + body
    signature = signing_key.sign(signed_message).signature.hex()
    return {
        "Content-Type": "application/json",
        "X-Signature-Ed25519": signature,
        "X-Signature-Timestamp": timestamp,
    }


@pytest.mark.asyncio
async def test_muv_button_to_prepared_result_and_offer_webhook_e2e(
    mock_logger, temp_dir, monkeypatch
):
    signing = pytest.importorskip("nacl.signing")
    signing_key = signing.SigningKey.generate()

    received = {"alerts": [], "results": []}
    whitelist = [
        {
            "BrandName": "Rolex",
            "BrandId": 1,
            "ModelName": "Daytona",
            "ModelId": 66,
            "RefMP": 1,
        }
    ]
    whitelist_payload = base64.b64encode(
        quote(json.dumps(whitelist)).encode("utf-8")
    ).decode("utf-8")

    async def muv_homepage(_request):
        return web.Response(
            text=f"<script>whitelistPayload = '{whitelist_payload}'</script>"
        )

    async def alert_webhook(request):
        received["alerts"].append(await request.json())
        return web.Response(status=204)

    async def result_webhook(request):
        received["results"].append(await request.json())
        return web.Response(status=204)

    fake_app = web.Application()
    fake_app.router.add_get("/", muv_homepage)
    fake_app.router.add_post("/alert", alert_webhook)
    fake_app.router.add_post("/result", result_webhook)
    fake_runner, fake_base_url = await _start_site(fake_app)

    store = ActionStore(str(temp_dir / "muv_actions.sqlite3"))
    discord_server = None
    try:
        monkeypatch.setattr(APP_CONFIG, "enable_notifications", True)
        monkeypatch.setattr(APP_CONFIG, "enable_muv_actions", True)
        monkeypatch.setattr(APP_CONFIG, "muv_action_label", "Send to MUV")
        monkeypatch.setattr(APP_CONFIG, "action_token_secret", "shared-secret")
        monkeypatch.setattr(APP_CONFIG, "muv_base_url", fake_base_url)
        monkeypatch.setattr(
            APP_CONFIG, "muv_result_webhook_url", f"{fake_base_url}/result"
        )
        monkeypatch.setattr(APP_CONFIG, "muv_auto_submit", False)
        monkeypatch.setattr(APP_CONFIG, "muv_submission_mode", "prepare")
        monkeypatch.setattr(APP_CONFIG, "muv_match_threshold", 0.72)
        monkeypatch.setattr(APP_CONFIG, "muv_min_picture_count", 3)
        monkeypatch.setattr(APP_CONFIG, "muv_default_condition", 3)
        monkeypatch.setattr(APP_CONFIG, "muv_seller_email", "")
        monkeypatch.setattr(APP_CONFIG, "muv_seller_first_name", "")
        monkeypatch.setattr(APP_CONFIG, "muv_seller_last_name", "")
        monkeypatch.setattr(APP_CONFIG, "muv_accept_terms", False)
        monkeypatch.setattr(APP_CONFIG, "muv_confirm_eu_seller", False)
        monkeypatch.setattr(
            APP_CONFIG,
            "discord_public_key",
            signing_key.verify_key.encode().hex(),
        )
        monkeypatch.setattr(
            APP_CONFIG,
            "discord_interactions_host",
            "127.0.0.1",
        )
        monkeypatch.setattr(APP_CONFIG, "discord_interactions_port", 0)
        monkeypatch.setattr(
            APP_CONFIG, "discord_interactions_path", "/discord/interactions"
        )
        monkeypatch.setattr(
            APP_CONFIG,
            "muv_offer_webhook_path",
            "/muv/offers",
        )
        monkeypatch.setenv("E2E_WEBHOOK_URL", f"{fake_base_url}/alert")

        site_config = SiteConfig(
            name="E2E",
            key="e2e",
            url=f"{fake_base_url}/listing",
            webhook_env_var="E2E_WEBHOOK_URL",
            color=0x123456,
            base_url=fake_base_url,
        )
        watch = WatchData(
            title="Rolex Daytona 116500LN",
            url=f"{fake_base_url}/listing/daytona",
            site_name="E2E",
            site_key="e2e",
            brand="Rolex",
            model="Daytona",
            reference="116500LN",
            price=Decimal("25000"),
            currency="EUR",
            image_url=f"{fake_base_url}/image.jpg",
            has_box=True,
            has_papers=True,
        )

        async with aiohttp.ClientSession() as session:
            notifications = NotificationManager(session, mock_logger, store)
            sent = await notifications.send_notifications([watch], site_config)

            assert sent == 1
            assert len(received["alerts"]) == 1
            button = received["alerts"][0]["components"][0]["components"][0]
            assert button["label"] == "Send to MUV"
            custom_id = button["custom_id"]
            action_id = custom_id.split(":")[1]

            muv_service = MUVActionService(session, store, mock_logger)
            discord_server = DiscordInteractionServer(
                store,
                muv_service,
                mock_logger,
            )
            await discord_server.start()
            port = discord_server._site._server.sockets[0].getsockname()[1]

            interaction = {
                "id": "interaction-1",
                "type": 3,
                "data": {"custom_id": custom_id},
                "member": {"user": {"id": "123", "username": "tester"}},
            }
            body = json.dumps(interaction).encode("utf-8")
            response = await session.post(
                f"http://127.0.0.1:{port}/discord/interactions",
                data=body,
                headers=_signed_headers(signing_key, body),
            )
            assert response.status == 200
            response_payload = await response.json()
            assert "queued" in response_payload["data"]["content"]

            await asyncio.gather(*list(discord_server._tasks))
            record = store.get(action_id)
            assert record.status == "prepared"
            assert record.result["muv"]["model_id"] == 66
            assert len(received["results"]) == 1
            prepared_embed = received["results"][0]["embeds"][0]
            assert prepared_embed["title"].startswith(
                "MUV request prepared: Rolex Daytona"
            )
            assert prepared_embed["image"]["url"] == f"{fake_base_url}/image.jpg"
            prepared_fields = {
                field["name"]: field["value"] for field in prepared_embed["fields"]
            }
            assert prepared_fields["💰 Listing Price:"] == "**€25.000**"
            assert prepared_fields["Original Listing:"] == (
                f"[**Open listing**]({fake_base_url}/listing/daytona)"
            )
            assert "MUV Match:" in prepared_fields
            assert "Submit Mode:" in prepared_fields
            assert all(
                "Chrono24 Search" not in field["name"]
                for field in prepared_embed["fields"]
            )

            offer_response = await session.post(
                f"http://127.0.0.1:{port}/muv/offers",
                json={
                    "action_id": action_id,
                    "price": "23000",
                    "currency": "EUR",
                    "muv_url": f"{fake_base_url}/sell",
                },
                headers={"X-MUV-Action-Secret": "shared-secret"},
            )
            assert offer_response.status == 200
            record = store.get(action_id)
            assert record.status == "completed"
            assert record.result["muv_offer"]["price"] == "23000"
            assert len(received["results"]) == 2
            offer_embed = received["results"][1]["embeds"][0]
            assert offer_embed["title"].startswith("MUV offer received: Rolex Daytona")
            offer_fields = {
                field["name"]: field["value"] for field in offer_embed["fields"]
            }
            assert offer_fields["💰 MUV Offer:"] == "**€23.000**"
            assert offer_fields["Spread:"] == "**-€2.000 / -8.0%**"
            offer_text = "\n".join(
                f"{field['name']}\n{field['value']}" for field in offer_embed["fields"]
            )
            assert "Chrono24 Search" not in offer_text
            assert "Submit Requirements" not in offer_text
            assert "MUV_AUTO_SUBMIT" not in offer_text
    finally:
        if discord_server:
            await discord_server.stop()
        store.close()
        await fake_runner.cleanup()
