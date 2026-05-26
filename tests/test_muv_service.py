"""Tests for MUV mapping and action processing."""

import base64
import json
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
    mock_config.muv_offer_link_urls = ""
    mock_config.muv_offer_link_poll_seconds = 900


def _offer_page_html(*, price=None, reviewed=True):
    watch = {
        "watchDetails": {
            "brand": "Breitling",
            "model": "Navitimer" if price else "Cockpit",
            "referenceNumber": "A26322" if price else None,
            "conditionStringValue": "Fine",
            "scopeOfDeliveryStringValue": "WatchOnly",
            "pictureUrl": "https://example.com/watch.jpg",
            "offeredWatchId": "watch-1",
        },
        "isReviewed": reviewed,
        "isDirectPurchasePossible": price is not None,
        "isCommissionDealPossible": False,
        "isAcceptedForPurchase": price is not None,
        "isNegotiated": False,
        "isReadyToProceed": False,
    }
    if price is not None:
        watch["offeredPurchasePrice"] = price

    values = [
        False,
        {
            "offerRequest": {
                "requestId": "request-1",
                "shortReference": 6955,
                "createdUTC": "2025-08-08T18:00:39.8393413",
                "isCanceled": False,
                "reviewStep": {
                    "isReviewed": reviewed,
                    "watches": [watch],
                    "offerExpiryDateUTC": "2025-08-18T00:00:00",
                    "isOfferExpired": True,
                },
            }
        },
    ]
    encoded = base64.b64encode(json.dumps(values).encode("utf-8")).decode("utf-8")
    return f'<!--Blazor:{{"parameterValues":"{encoded}"}}-->'


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


def test_parse_offer_page_extracts_direct_purchase_offer():
    payload = MUVActionService.parse_offer_page(
        _offer_page_html(price=3000),
        "https://www.meineuhrverkaufen.de/Sell/request-1?mt=token",
    )

    assert payload["status"] == "offered"
    assert payload["price"] == "3,000"
    assert payload["currency"] == "EUR"
    assert payload["watches"][0]["model"] == "Navitimer"
    assert payload["watches"][0]["price_display"] == "3,000"


def test_parse_offer_page_extracts_rejection():
    payload = MUVActionService.parse_offer_page(
        _offer_page_html(price=None),
        "https://www.meineuhrverkaufen.de/Sell/request-1?mt=token",
    )

    assert payload["status"] == "rejected"
    assert "price" not in payload
    assert payload["watches"][0]["model"] == "Cockpit"
    assert payload["watches"][0]["status"] == "rejected"


@pytest.mark.asyncio
async def test_monitor_offer_links_notifies_only_changed_state(
    mock_logger, temp_dir, monkeypatch
):
    store = ActionStore(str(temp_dir / "actions.sqlite3"))
    try:
        url = "https://www.meineuhrverkaufen.de/Sell/request-1?mt=token"
        store.save_offer_link(url)
        html_by_round = [
            _offer_page_html(price=3000),
            _offer_page_html(price=3000),
            _offer_page_html(price=3200),
        ]
        round_index = {"value": 0}

        async def fake_fetch_page(_session, _url, _logger):
            return html_by_round[round_index["value"]]

        sent = []

        async def fake_send_result_webhook(record, result):
            sent.append((record, result))

        service = MUVActionService(None, store, mock_logger)
        monkeypatch.setattr("muv_service.fetch_page", fake_fetch_page)
        monkeypatch.setattr(service, "_send_result_webhook", fake_send_result_webhook)

        assert await service.monitor_offer_links() == 1
        assert await service.monitor_offer_links() == 0
        round_index["value"] = 2
        assert await service.monitor_offer_links() == 1

        assert [result.data["muv_offer"]["price"] for _, result in sent] == [
            "3,000",
            "3,200",
        ]
    finally:
        store.close()
