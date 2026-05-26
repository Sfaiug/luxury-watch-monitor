"""Discord interaction endpoint for VM-side MUV button actions."""

import asyncio
from hmac import compare_digest as hmac_compare
import json
from typing import Any, Dict, Optional, Set

from aiohttp import web

from action_store import ActionStore
from config import APP_CONFIG
from muv_service import MUVActionService

INTERACTION_PING = 1
INTERACTION_MESSAGE_COMPONENT = 3

RESPONSE_PONG = 1
RESPONSE_CHANNEL_MESSAGE = 4

EPHEMERAL_FLAG = 64


def verify_discord_signature(
    public_key: str, signature: str, timestamp: str, body: bytes
) -> bool:
    """Verify Discord's Ed25519 interaction signature against the raw body."""
    if not public_key or not signature or not timestamp:
        return False

    try:
        from nacl.signing import VerifyKey
        from nacl.exceptions import BadSignatureError

        verify_key = VerifyKey(bytes.fromhex(public_key))
        verify_key.verify(timestamp.encode("utf-8") + body, bytes.fromhex(signature))
        return True
    except (ValueError, BadSignatureError):
        return False


class DiscordInteractionServer:
    """Small aiohttp server for Discord application interactions."""

    def __init__(self, store: ActionStore, muv_service: MUVActionService, logger):
        self.store = store
        self.muv_service = muv_service
        self.logger = logger
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._tasks: Set[asyncio.Task] = set()

    async def start(self):
        if not APP_CONFIG.discord_public_key:
            raise ValueError(
                "DISCORD_PUBLIC_KEY is required when DISCORD_INTERACTIONS_ENABLED=true"
            )

        app = web.Application(client_max_size=512 * 1024)
        app.router.add_post(APP_CONFIG.discord_interactions_path, self.handle_request)
        app.router.add_post(APP_CONFIG.muv_offer_webhook_path, self.handle_muv_offer)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(
            self._runner,
            APP_CONFIG.discord_interactions_host,
            APP_CONFIG.discord_interactions_port,
        )
        await self._site.start()
        self.logger.info(
            "Discord interaction server listening on %s:%s%s and %s",
            APP_CONFIG.discord_interactions_host,
            APP_CONFIG.discord_interactions_port,
            APP_CONFIG.discord_interactions_path,
            APP_CONFIG.muv_offer_webhook_path,
        )

    async def stop(self):
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        if self._runner:
            await self._runner.cleanup()
            self._runner = None
            self._site = None

    async def handle_request(self, request: web.Request) -> web.Response:
        body = await request.read()
        signature = request.headers.get("X-Signature-Ed25519", "")
        timestamp = request.headers.get("X-Signature-Timestamp", "")

        if not verify_discord_signature(
            APP_CONFIG.discord_public_key, signature, timestamp, body
        ):
            return web.Response(status=401, text="invalid signature")

        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return web.Response(status=400, text="invalid json")

        response_payload = await self.handle_payload(payload)
        return web.json_response(response_payload)

    async def handle_muv_offer(self, request: web.Request) -> web.Response:
        if not APP_CONFIG.action_token_secret:
            return web.json_response(
                {"error": "ACTION_TOKEN_SECRET is required"}, status=503
            )

        supplied_secret = request.headers.get(
            "X-MUV-Action-Secret"
        ) or request.query.get("secret")
        if not supplied_secret or not hmac_compare(
            supplied_secret, APP_CONFIG.action_token_secret
        ):
            return web.json_response({"error": "invalid secret"}, status=401)

        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "invalid json"}, status=400)

        action_id = payload.get("action_id")
        if not action_id and payload.get("custom_id"):
            action_id = ActionStore.parse_custom_id(
                payload["custom_id"], APP_CONFIG.action_token_secret
            )
        if not action_id and payload.get("muv_url"):
            result = await self.muv_service.publish_offer_link(payload["muv_url"])
            status = 200 if result.status != "failed" else 422
            return web.json_response(
                {"status": result.status, "error": result.error}, status=status
            )
        if not action_id:
            return web.json_response({"error": "action_id is required"}, status=400)

        result = await self.muv_service.publish_offer(action_id, payload)
        status = 200 if result.status == "completed" else 404
        return web.json_response(
            {"status": result.status, "error": result.error}, status=status
        )

    async def handle_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        interaction_type = payload.get("type")
        if interaction_type == INTERACTION_PING:
            return {"type": RESPONSE_PONG}

        if interaction_type != INTERACTION_MESSAGE_COMPONENT:
            return self._ephemeral("Unsupported interaction type.")

        custom_id = (payload.get("data") or {}).get("custom_id", "")
        action_id = ActionStore.parse_custom_id(
            custom_id, APP_CONFIG.action_token_secret
        )
        if not action_id:
            return self._ephemeral("Unknown action.")

        user = self._extract_user(payload)
        queued, record = self.store.queue_action(
            action_id,
            requested_by=user.get("id"),
            requested_by_name=user.get("name"),
            interaction_id=payload.get("id"),
        )

        if not record:
            return self._ephemeral("This MUV action is no longer available on the VM.")

        if not queued:
            return self._ephemeral(f"MUV action is already `{record.status}`.")

        task = asyncio.create_task(self._run_action(action_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

        title = record.listing.get("title") or "this listing"
        return self._ephemeral(f"MUV action queued on the VM for **{title[:120]}**.")

    async def _run_action(self, action_id: str):
        try:
            await self.muv_service.handle_action(action_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.logger.exception(
                "Unhandled background MUV action failure for %s: %s", action_id, exc
            )

    @staticmethod
    def _extract_user(payload: Dict[str, Any]) -> Dict[str, Optional[str]]:
        user = (payload.get("member") or {}).get("user") or payload.get("user") or {}
        name = user.get("global_name") or user.get("username")
        return {"id": user.get("id"), "name": name}

    @staticmethod
    def _ephemeral(content: str) -> Dict[str, Any]:
        return {
            "type": RESPONSE_CHANNEL_MESSAGE,
            "data": {
                "content": content,
                "flags": EPHEMERAL_FLAG,
            },
        }
