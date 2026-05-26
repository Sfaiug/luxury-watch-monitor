"""Tests for MUV mapping and action processing."""

from decimal import Decimal
from unittest.mock import patch

import pytest

from action_store import ActionStore
from models import WatchData
from muv_service import MUVActionService


def _configure_muv(mock_config, *, auto_submit=False):
    mock_config.muv_base_url = "https://www.meineuhrverkaufen.de"
    mock_config.muv_submission_mode = "prepare"
    mock_config.muv_auto_submit = auto_submit
    mock_config.muv_match_threshold = 0.72
    mock_config.muv_min_picture_count = 3
    mock_config.muv_default_condition = 3
    mock_config.muv_seller_email = ""
    mock_config.muv_seller_first_name = ""
    mock_config.muv_seller_last_name = ""
    mock_config.muv_accept_terms = False
    mock_config.muv_confirm_eu_seller = False
    mock_config.muv_result_webhook_url = ""


@pytest.mark.asyncio
async def test_match_listing_exact_model(mock_logger):
    service = MUVActionService(None, None, mock_logger)
    service._whitelist = [
        {
            "BrandName": "Rolex",
            "BrandId": 1,
            "ModelName": "Daytona",
            "ModelId": 66,
            "RefMP": 1,
        }
    ]

    with patch("muv_service.APP_CONFIG") as mock_config:
        _configure_muv(mock_config)

        match = await service.match_listing(
            {
                "brand": "Rolex",
                "model": "Daytona",
                "title": "Rolex Daytona 116500LN",
            }
        )

    assert match is not None
    assert match.model_id == 66
    assert match.confidence >= 0.9


@pytest.mark.asyncio
async def test_handle_action_prepares_request_when_auto_submit_disabled(
    mock_logger, temp_dir
):
    store = ActionStore(str(temp_dir / "actions.sqlite3"))
    try:
        watch = WatchData(
            title="Rolex Daytona 116500LN",
            url="https://example.com/daytona",
            site_name="Example",
            site_key="example",
            brand="Rolex",
            model="Daytona",
            reference="116500LN",
            price=Decimal("25000"),
            image_url="https://example.com/watch.jpg",
            has_box=True,
            has_papers=True,
        )
        action_id = store.save_watch(watch)
        store.queue_action(action_id, "123", "tester", "interaction-1")

        service = MUVActionService(None, store, mock_logger)
        service._whitelist = [
            {
                "BrandName": "Rolex",
                "BrandId": 1,
                "ModelName": "Daytona",
                "ModelId": 66,
                "RefMP": 1,
            }
        ]

        with patch("muv_service.APP_CONFIG") as mock_config:
            _configure_muv(mock_config, auto_submit=False)

            result = await service.handle_action(action_id)

        record = store.get(action_id)
        assert result.status == "prepared"
        assert record.status == "prepared"
        assert record.result["muv"]["model_id"] == 66
        assert "MUV_AUTO_SUBMIT is false" in record.result["validation_errors"]
    finally:
        store.close()


@pytest.mark.asyncio
async def test_handle_action_fails_when_no_model_match(mock_logger, temp_dir):
    store = ActionStore(str(temp_dir / "actions.sqlite3"))
    try:
        action_id = store.save_watch(
            WatchData(
                title="Unknown Watch",
                url="https://example.com/watch",
                site_name="Example",
                site_key="example",
            )
        )
        service = MUVActionService(None, store, mock_logger)
        service._whitelist = [
            {
                "BrandName": "Rolex",
                "BrandId": 1,
                "ModelName": "Daytona",
                "ModelId": 66,
                "RefMP": 1,
            }
        ]

        with patch("muv_service.APP_CONFIG") as mock_config:
            _configure_muv(mock_config)

            result = await service.handle_action(action_id)

        assert result.status == "failed"
        assert "No MUV model match" in result.error
    finally:
        store.close()


@pytest.mark.asyncio
async def test_publish_offer_links_price_to_original_listing(mock_logger, temp_dir):
    store = ActionStore(str(temp_dir / "actions.sqlite3"))
    try:
        action_id = store.save_watch(
            WatchData(
                title="Rolex Daytona 116500LN",
                url="https://example.com/daytona",
                site_name="Example",
                site_key="example",
                brand="Rolex",
                model="Daytona",
                price=Decimal("25000"),
            )
        )
        service = MUVActionService(None, store, mock_logger)

        with patch("muv_service.APP_CONFIG") as mock_config:
            _configure_muv(mock_config)

            result = await service.publish_offer(
                action_id,
                {
                    "price": "23000",
                    "currency": "EUR",
                    "muv_url": "https://www.meineuhrverkaufen.de/sell",
                },
            )

        record = store.get(action_id)
        assert result.status == "completed"
        assert record.status == "completed"
        assert record.result["muv_offer"]["price"] == "23000"
        assert record.result["listing"]["url"] == "https://example.com/daytona"
    finally:
        store.close()
