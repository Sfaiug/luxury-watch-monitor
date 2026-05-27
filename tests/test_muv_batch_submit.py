"""Tests for the guarded MUV Discord batch runner."""

import asyncio
from decimal import Decimal

from action_store import ActionStore
from scripts import muv_batch_submit as batch


class NeverSubmitService:
    async def handle_action(self, action_id):
        raise AssertionError(f"unexpected MUV submit for {action_id}")


def _message(*, custom_id="muv:action-1"):
    return {
        "id": "msg-1",
        "timestamp": "2026-05-27T14:59:34.241000+00:00",
        "channel_name": "grimmeissen",
        "embeds": [
            {
                "title": "Rolex Daytona | 116500LN",
                "url": "https://example.com/daytona",
                "image": "https://example.com/daytona.jpg",
                "footer": "Grimmeissen - Detected: 2026-05-27 14:59:34",
                "fields": [
                    {"name": "💰 Price:", "value": "**€25.000**"},
                    {"name": "🗓️ Year:", "value": "**2024**"},
                    {"name": "📦 Box:", "value": "**✅**"},
                    {"name": "📄 Papers:", "value": "**❌**"},
                    {"name": "🔩 Case Material:", "value": "**Steel**"},
                    {"name": "📏 Diameter:", "value": "**40mm**"},
                ],
            }
        ],
        "components": [
            {
                "type": 1,
                "components": [
                    {
                        "type": 2,
                        "style": 1,
                        "label": "Send to MUV",
                        "custom_id": custom_id,
                    }
                ],
            }
        ],
    }


def test_watch_from_embed_parses_listing_fields():
    watch = batch.watch_from_embed(_message(), _message()["embeds"][0])

    assert watch.title == "Rolex Daytona | 116500LN"
    assert watch.brand == "Rolex"
    assert watch.model == "Daytona"
    assert watch.reference == "116500LN"
    assert watch.price == Decimal("25000")
    assert watch.has_box is True
    assert watch.has_papers is False
    assert watch.case_material == "Steel"
    assert watch.image_url == "https://example.com/daytona.jpg"


def test_watch_from_embed_extracts_bachmann_reference_from_url():
    message = _message()
    embed = message["embeds"][0]
    embed["title"] = "Jaeger-LeCoultre Reverso Tribute Monoface"
    embed["url"] = (
        "https://www.bachmann-scher.de/gebrauchte-luxusuhren-kaufen/"
        "jaeger-lecoultre-reverso-tribute-monoface-ref-q7168420-stainless-steel-"
        "box-papers-bj-2025-new-like-17624.html"
    )
    embed["footer"] = "Bachmann & Scher - Detected: 2026-05-27 16:38:37"

    watch = batch.watch_from_embed(message, embed)

    assert watch.reference == "Q7168420"


def test_latest_items_uses_signed_button_action_id(mocker):
    mocker.patch.object(batch.APP_CONFIG, "action_token_secret", "secret")
    custom_id = ActionStore.custom_id("signed-action", "secret")

    items = batch.latest_items([_message(custom_id=custom_id)], limit=100)

    assert len(items) == 1
    assert items[0].action_id == "signed-action"


def test_save_batch_items_persists_exact_action_id(temp_dir):
    store = ActionStore(str(temp_dir / "actions.sqlite3"))
    try:
        item = batch.latest_items([_message(custom_id="muv:action-1")], limit=100)[0]

        assert batch.save_batch_items(store, [item]) == 1
        record = store.get("action-1")

        assert record is not None
        assert record.status == "not_requested"
        assert record.listing["title"] == "Rolex Daytona | 116500LN"
    finally:
        store.close()


def test_save_listing_does_not_reset_existing_status(temp_dir):
    store = ActionStore(str(temp_dir / "actions.sqlite3"))
    try:
        item = batch.latest_items([_message(custom_id="muv:action-1")], limit=100)[0]
        batch.save_batch_items(store, [item])
        store.update_status("action-1", "prepared", result={"ok": True})

        batch.save_batch_items(store, [item])
        record = store.get("action-1")

        assert record.status == "prepared"
        assert record.result == {"ok": True}
    finally:
        store.close()


def test_submission_config_errors_include_missing_required_contact(mocker):
    mocker.patch.object(batch.APP_CONFIG, "muv_submission_mode", "prepare")
    mocker.patch.object(batch.APP_CONFIG, "muv_auto_submit", False)
    mocker.patch.object(batch.APP_CONFIG, "muv_seller_email", "")
    mocker.patch.object(batch.APP_CONFIG, "muv_seller_first_name", "")
    mocker.patch.object(batch.APP_CONFIG, "muv_seller_last_name", "")
    mocker.patch.object(batch.APP_CONFIG, "muv_accept_terms", True)
    mocker.patch.object(batch.APP_CONFIG, "muv_confirm_eu_seller", True)

    errors = batch.submission_config_errors()

    assert "MUV_SUBMISSION_MODE must be browser" in errors
    assert "MUV_AUTO_SUBMIT must be true" in errors
    assert "MUV_SELLER_EMAIL is missing" in errors
    assert "MUV_ACCEPT_TERMS must be true" not in errors


def test_submission_config_errors_accept_requester_profile(mocker):
    mocker.patch.object(batch.APP_CONFIG, "muv_submission_mode", "browser")
    mocker.patch.object(batch.APP_CONFIG, "muv_auto_submit", True)
    mocker.patch.object(batch.APP_CONFIG, "muv_seller_email", "")
    mocker.patch.object(batch.APP_CONFIG, "muv_seller_first_name", "")
    mocker.patch.object(batch.APP_CONFIG, "muv_seller_last_name", "")
    mocker.patch.object(
        batch.APP_CONFIG,
        "muv_seller_profiles_json",
        '{"user-1":{"email":"user@example.com","firstName":"Ada","lastName":"Lovelace"}}',
    )
    mocker.patch.object(batch.APP_CONFIG, "muv_accept_terms", True)
    mocker.patch.object(batch.APP_CONFIG, "muv_confirm_eu_seller", True)

    assert batch.submission_config_errors("user-1") == []


def test_submit_ready_skips_failed_record_with_existing_muv_url(temp_dir, mocker):
    mocker.patch.object(batch.APP_CONFIG, "muv_submission_mode", "browser")
    mocker.patch.object(batch.APP_CONFIG, "muv_auto_submit", True)
    mocker.patch.object(batch.APP_CONFIG, "muv_seller_email", "seller@example.com")
    mocker.patch.object(batch.APP_CONFIG, "muv_seller_first_name", "Ada")
    mocker.patch.object(batch.APP_CONFIG, "muv_seller_last_name", "Lovelace")
    mocker.patch.object(batch.APP_CONFIG, "muv_seller_profiles_json", "")
    mocker.patch.object(batch.APP_CONFIG, "muv_allowed_requester_ids", "")
    mocker.patch.object(batch.APP_CONFIG, "muv_accept_terms", True)
    mocker.patch.object(batch.APP_CONFIG, "muv_confirm_eu_seller", True)

    store = ActionStore(str(temp_dir / "actions.sqlite3"))
    muv_url = (
        "https://www.meineuhrverkaufen.de/Sell/c7db9d61-a30c-42c4-a693-49f50bf3d71d"
    )
    row = {
        "ready": True,
        "action_id": "action-1",
        "message_id": "msg-1",
        "title": "Rolex Datejust | 126334",
    }
    try:
        store.save_listing("action-1", {"title": row["title"]})
        store.update_status(
            "action-1",
            "failed",
            result={"muv_sell_url": muv_url},
            last_error="old false failure",
        )

        result = asyncio.run(
            batch.submit_ready_items(
                store,
                NeverSubmitService(),
                [row],
                requester_id="user-1",
                requester_name="Ada",
                max_submit=None,
            )
        )

        assert result["attempted"] == 0
        assert result["submitted"] == 0
        assert result["skipped"][0]["skip_reason"] == "already has MUV Sell link"
        assert result["skipped"][0]["muv_sell_url"] == muv_url
        assert store.list_offer_links()[0].url == muv_url
    finally:
        store.close()
