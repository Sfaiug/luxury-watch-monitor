"""Tests for MUV mapping and action processing."""

import base64
import json
from decimal import Decimal
from unittest.mock import patch

import pytest

from action_store import ActionStore
from models import WatchData
from muv_service import MUVActionService, MUVMatch, MUVResult


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
    mock_config.muv_dm_results_to_requester = False
    mock_config.muv_result_delivery_mode = "channel_and_dm"
    mock_config.muv_seller_profiles_json = ""
    mock_config.muv_allowed_requester_ids = ""
    mock_config.discord_bot_token = ""
    mock_config.discord_api_base_url = "https://discord.com/api/v10"


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


def test_validate_for_submit_accepts_full_image_gallery(mock_logger):
    service = MUVActionService(None, None, mock_logger)
    listing = {
        "image_urls": [
            "https://example.com/watch-1.jpg",
            "https://example.com/watch-2.jpg",
            "https://example.com/watch-3.jpg",
        ]
    }

    with patch("muv_service.APP_CONFIG") as mock_config:
        _configure_muv(mock_config, auto_submit=True)
        mock_config.muv_seller_email = "seller@example.com"
        mock_config.muv_seller_first_name = "Ada"
        mock_config.muv_seller_last_name = "Lovelace"
        mock_config.muv_accept_terms = True
        mock_config.muv_confirm_eu_seller = True

        assert service._validate_for_submit(listing) == []


def test_scope_and_condition_use_muv_option_values(mock_logger):
    service = MUVActionService(None, None, mock_logger)
    match = MUVMatch(
        brand_name="Rolex",
        brand_id=1,
        model_name="Datejust",
        model_id=2,
        ref_mp=3,
        confidence=1.0,
    )
    listing = {
        "condition": "Fine",
        "has_box": True,
        "has_papers": True,
        "image_urls": [
            "https://example.com/watch-1.jpg",
            "https://example.com/watch-2.jpg",
            "https://example.com/watch-3.jpg",
        ],
    }

    with patch("muv_service.APP_CONFIG") as mock_config:
        _configure_muv(mock_config, auto_submit=True)

        payload = service._build_request_payload(listing, match)

    assert payload["condition"] == "Fine"
    assert payload["scopeOfDelivery"] == "WatchWithBoxAndPapers"
    assert MUVActionService._map_scope(False, False) == "WatchOnly"
    assert MUVActionService._map_scope(True, False) == "WatchWithBox"
    assert MUVActionService._map_scope(False, True) == "WatchWithPapers"


def test_unique_muv_sell_url_accepts_submitted_and_review_links():
    assert MUVActionService._is_unique_muv_sell_url(
        "https://www.meineuhrverkaufen.de/Sell/c7db9d61-a30c-42c4-a693-49f50bf3d71d"
    )
    assert MUVActionService._is_unique_muv_sell_url(
        "https://www.meineuhrverkaufen.de/Sell/3de83199-b7d9-475c-a3e8-72c86693ecff?mt=b79bee79-7444-4ebb-e0d7-08de01b936c3"
    )
    assert not MUVActionService._is_unique_muv_sell_url(
        "https://www.meineuhrverkaufen.de/sell"
    )


def test_allowed_requester_ids_block_other_discord_users(mock_logger):
    service = MUVActionService(None, None, mock_logger)
    listing = {
        "image_urls": [
            "https://example.com/watch-1.jpg",
            "https://example.com/watch-2.jpg",
            "https://example.com/watch-3.jpg",
        ],
    }
    allowed = type("Record", (), {"requested_by": "user-1"})()
    blocked = type("Record", (), {"requested_by": "user-2"})()

    with patch("muv_service.APP_CONFIG") as mock_config:
        _configure_muv(mock_config, auto_submit=True)
        mock_config.muv_seller_email = "seller@example.com"
        mock_config.muv_seller_first_name = "Ada"
        mock_config.muv_seller_last_name = "Lovelace"
        mock_config.muv_accept_terms = True
        mock_config.muv_confirm_eu_seller = True
        mock_config.muv_allowed_requester_ids = "user-1"

        assert service._validate_for_submit(listing, allowed) == []
        assert (
            "Discord user is not allowed to submit to MUV"
            in service._validate_for_submit(listing, blocked)
        )


def test_build_request_payload_uses_requester_seller_profile(mock_logger):
    service = MUVActionService(None, None, mock_logger)
    record = type(
        "Record",
        (),
        {"requested_by": "user-1"},
    )()
    match = MUVMatch(
        brand_name="Rolex",
        brand_id=1,
        model_name="Daytona",
        model_id=2,
        ref_mp=3,
        confidence=1.0,
    )
    listing = {
        "reference": "116500LN",
        "image_urls": [
            "https://example.com/watch-1.jpg",
            "https://example.com/watch-2.jpg",
            "https://example.com/watch-3.jpg",
        ],
    }

    with patch("muv_service.APP_CONFIG") as mock_config:
        _configure_muv(mock_config, auto_submit=True)
        mock_config.muv_accept_terms = True
        mock_config.muv_confirm_eu_seller = True
        mock_config.muv_seller_profiles_json = json.dumps(
            {
                "user-1": {
                    "email": "buyer@example.com",
                    "first_name": "Ada",
                    "last_name": "Lovelace",
                }
            }
        )

        payload = service._build_request_payload(listing, match, record)
        errors = service._validate_for_submit(listing, record)

    assert payload["seller"] == {
        "email": "buyer@example.com",
        "firstName": "Ada",
        "lastName": "Lovelace",
    }
    assert errors == []


def test_validate_for_submit_blocks_unknown_requester_when_profiles_configured(
    mock_logger,
):
    service = MUVActionService(None, None, mock_logger)
    record = type(
        "Record",
        (),
        {"requested_by": "user-without-profile"},
    )()
    listing = {
        "image_urls": [
            "https://example.com/watch-1.jpg",
            "https://example.com/watch-2.jpg",
            "https://example.com/watch-3.jpg",
        ],
    }

    with patch("muv_service.APP_CONFIG") as mock_config:
        _configure_muv(mock_config, auto_submit=True)
        mock_config.muv_seller_email = "global@example.com"
        mock_config.muv_seller_first_name = "Global"
        mock_config.muv_seller_last_name = "Seller"
        mock_config.muv_accept_terms = True
        mock_config.muv_confirm_eu_seller = True
        mock_config.muv_seller_profiles_json = json.dumps(
            {
                "other-user": {
                    "email": "other@example.com",
                    "firstName": "Other",
                    "lastName": "Seller",
                }
            }
        )

        errors = service._validate_for_submit(listing, record)

    assert "MUV_SELLER_EMAIL is missing" in errors
    assert "MUV_SELLER_FIRST_NAME is missing" in errors
    assert "MUV_SELLER_LAST_NAME is missing" in errors


@pytest.mark.asyncio
async def test_listing_with_submission_images_collects_detail_gallery(
    mock_logger, monkeypatch
):
    detail_html = """
    <html>
      <head>
        <meta property="og:image" content="/media/watch-og.jpg">
        <script type="application/ld+json">
          {"@type":"Product","image":["/gallery/watch-2.webp",{"url":"/files/watch-3.jpg"}]}
        </script>
      </head>
      <body>
        <img src="/assets/logo.svg">
        <img data-src="/uploads/watch-4.jpg">
        <source srcset="/img/watch-5.jpg 1x, /img/watch-5@2x.jpg 2x">
      </body>
    </html>
    """

    async def fake_fetch_page(_session, url, _logger):
        assert url == "https://dealer.test/watch"
        return detail_html

    service = MUVActionService(object(), None, mock_logger)
    monkeypatch.setattr("muv_service.fetch_page", fake_fetch_page)

    with patch("muv_service.APP_CONFIG") as mock_config:
        _configure_muv(mock_config)

        listing = await service._listing_with_submission_images(
            {
                "url": "https://dealer.test/watch",
                "image_url": "https://dealer.test/media/watch-1.jpg",
            }
        )

    assert listing["image_url"] == "https://dealer.test/media/watch-1.jpg"
    assert listing["image_urls"][:4] == [
        "https://dealer.test/media/watch-1.jpg",
        "https://dealer.test/gallery/watch-2.webp",
        "https://dealer.test/files/watch-3.jpg",
        "https://dealer.test/media/watch-og.jpg",
    ]
    assert "https://dealer.test/assets/logo.svg" not in listing["image_urls"]


def test_unique_muv_sell_url_detection_accepts_submission_and_review_urls():
    assert MUVActionService._is_unique_muv_sell_url(
        "https://www.meineuhrverkaufen.de/Sell/3de83199-b7d9-475c-a3e8-72c86693ecff?mt=b79bee79-7444-4ebb-e0d7-08de01b936c3"
    )
    assert MUVActionService._is_unique_muv_sell_url(
        "https://www.meineuhrverkaufen.de/Sell/0248613e-93ee-4b74-a8b3-28eab647c5c2?mt=e9dc6193-ddd3-45d8-5744-08de29bd80d2"
    )
    assert not MUVActionService._is_unique_muv_sell_url(
        "https://www.meineuhrverkaufen.de/sell"
    )
    assert MUVActionService._is_unique_muv_sell_url(
        "https://www.meineuhrverkaufen.de/Sell/3de83199-b7d9-475c-a3e8-72c86693ecff"
    )


def test_image_byte_detection_rejects_html_uploads():
    assert MUVActionService._looks_like_image_bytes(b"\xff\xd8\xff\xe0jpeg")
    assert MUVActionService._looks_like_image_bytes(b"\x89PNG\r\n\x1a\npng")
    assert MUVActionService._looks_like_image_bytes(
        b"\xff\xd8\xff\xe0application-octet-stream-jpeg"
    )
    assert not MUVActionService._looks_like_image_bytes(b"<html>not an image</html>")


def test_submission_image_url_filter_handles_cdn_and_placeholders():
    assert MUVActionService._looks_like_submission_image(
        "https://d29ueykkv8fpnq.cloudfront.net/ml18yhav6jc1n6jfbtqjhborunoe"
    )
    assert not MUVActionService._listing_image_urls(
        {
            "image_url": "https://dealer.test/typo3temp/csm_Foto-in-Bearbeitung_340x255.jpg"
        }
    )


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
async def test_match_listing_maps_vintage_heuer_carrera_to_tag_heuer(mock_logger):
    service = MUVActionService(None, None, mock_logger)
    service._whitelist = [
        {
            "BrandName": "Heuer",
            "BrandId": 27,
            "ModelName": "Skipper",
            "ModelId": 490,
            "RefMP": 1,
        },
        {
            "BrandName": "Tag Heuer",
            "BrandId": 43,
            "ModelName": "Carrera",
            "ModelId": 814,
            "RefMP": 1,
        },
    ]

    with patch("muv_service.APP_CONFIG") as mock_config:
        _configure_muv(mock_config)

        match = await service.match_listing(
            {
                "brand": "Heuer",
                "model": "Carrera",
                "reference": "1153",
                "title": "Heuer Carrera | 1153",
            }
        )

    assert match is not None
    assert match.brand_name == "Tag Heuer"
    assert match.model_name == "Carrera"


@pytest.mark.asyncio
async def test_match_listing_keeps_true_heuer_models(mock_logger):
    service = MUVActionService(None, None, mock_logger)
    service._whitelist = [
        {
            "BrandName": "Heuer",
            "BrandId": 27,
            "ModelName": "Skipper",
            "ModelId": 490,
            "RefMP": 1,
        },
        {
            "BrandName": "Tag Heuer",
            "BrandId": 43,
            "ModelName": "Carrera",
            "ModelId": 814,
            "RefMP": 1,
        },
    ]

    with patch("muv_service.APP_CONFIG") as mock_config:
        _configure_muv(mock_config)

        match = await service.match_listing(
            {
                "brand": "Heuer",
                "model": "Skipper",
                "reference": "73463",
                "title": "Heuer Skipper | 73463",
            }
        )

    assert match is not None
    assert match.brand_name == "Heuer"
    assert match.model_name == "Skipper"


@pytest.mark.asyncio
async def test_match_listing_handles_production_brand_aliases(mock_logger):
    service = MUVActionService(None, None, mock_logger)
    service._whitelist = [
        {
            "BrandName": "Rolex",
            "BrandId": 1,
            "ModelName": "GMT-Master II",
            "ModelId": 68,
            "RefMP": 1,
        },
        {
            "BrandName": "Patek Philippe",
            "BrandId": 5,
            "ModelName": "Annual Calendar",
            "ModelId": 54,
            "RefMP": 1,
        },
        {
            "BrandName": "Audemars Piguet",
            "BrandId": 3,
            "ModelName": "Royal Oak",
            "ModelId": 13,
            "RefMP": 1,
        },
        {
            "BrandName": "Glashütte",
            "BrandId": 25,
            "ModelName": "Senator",
            "ModelId": 475,
            "RefMP": 1,
        },
        {
            "BrandName": "Chronoswiss",
            "BrandId": 16,
            "ModelName": "Flying Regulator",
            "ModelId": 323,
            "RefMP": 1,
        },
    ]

    cases = [
        (
            {
                "brand": "Rolex",
                "model": "GMT",
                "reference": "116710BLNR",
                "title": "Rolex GMT | 116710BLNR",
            },
            ("Rolex", "GMT-Master II"),
        ),
        (
            {
                "brand": "Patek Philippe",
                "model": "Jahreskalender",
                "reference": "5205R-011",
                "title": "Patek Philippe Jahreskalender | 5205R-011",
            },
            ("Patek Philippe", "Annual Calendar"),
        ),
        (
            {
                "brand": "Audemars Piguet",
                "model": "Off Shore Chrono",
                "reference": "25721ST/O/1000ST/01",
                "title": "Audemars Piguet Off Shore Chrono | 25721ST/O/1000ST/01",
            },
            ("Audemars Piguet", "Royal Oak"),
        ),
        (
            {
                "brand": "Glashütte Original",
                "model": "Senator Chronometer",
                "title": "Glashütte Original Senator Chronometer",
            },
            ("Glashütte", "Senator"),
        ),
        (
            {
                "brand": "Chronoswiss",
                "model": "Flying Grand Regulator",
                "title": "Chronoswiss Flying Grand Regulator",
            },
            ("Chronoswiss", "Flying Regulator"),
        ),
    ]

    with patch("muv_service.APP_CONFIG") as mock_config:
        _configure_muv(mock_config)

        for listing, expected in cases:
            match = await service.match_listing(listing)
            assert match is not None
            assert (match.brand_name, match.model_name) == expected


@pytest.mark.asyncio
async def test_match_listing_infers_brand_when_vendor_is_site_name(mock_logger):
    service = MUVActionService(None, None, mock_logger)
    service._whitelist = [
        {
            "BrandName": "Audemars Piguet",
            "BrandId": 3,
            "ModelName": "Royal Oak",
            "ModelId": 13,
            "RefMP": 1,
        }
    ]

    with patch("muv_service.APP_CONFIG") as mock_config:
        _configure_muv(mock_config)

        match = await service.match_listing(
            {
                "brand": "Watch Out",
                "site_name": "Watch Out",
                "model": "Audemars Piguet Royal Oak 14486",
                "reference": "KA57OB",
                "title": "Audemars Piguet Royal Oak 14486",
            }
        )

    assert match is not None
    assert match.brand_name == "Audemars Piguet"
    assert match.model_name == "Royal Oak"


@pytest.mark.asyncio
async def test_match_listing_does_not_force_unsupported_rolex_land_dweller(
    mock_logger,
):
    service = MUVActionService(None, None, mock_logger)
    service._whitelist = [
        {
            "BrandName": "Rolex",
            "BrandId": 1,
            "ModelName": "Sea-Dweller",
            "ModelId": 3,
            "RefMP": 1,
        },
        {
            "BrandName": "Rolex",
            "BrandId": 1,
            "ModelName": "Sky-Dweller",
            "ModelId": 73,
            "RefMP": 1,
        },
    ]

    with patch("muv_service.APP_CONFIG") as mock_config:
        _configure_muv(mock_config)

        match = await service.match_listing(
            {
                "brand": "Rolex",
                "model": "Land Dweller 36",
                "reference": "127234",
                "title": "Rolex Land Dweller 36 | 127234",
            }
        )

    assert match is None


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


def test_result_embed_reuses_original_listing_with_muv_fields(mock_logger, temp_dir):
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
                reference="116500LN",
                price=Decimal("25000"),
                currency="EUR",
                image_url="https://example.com/watch.jpg",
                condition="Fine",
                has_box=True,
                has_papers=True,
                case_material="Steel",
                diameter="40mm",
            )
        )
        record = store.get(action_id)
        service = MUVActionService(None, store, mock_logger)
        result = MUVResult(
            status="completed",
            title="MUV offer received",
            description="MUV returned an offer for the original listing.",
            data={
                "listing": record.listing,
                "muv_offer": {
                    "price": "23000",
                    "currency": "EUR",
                    "muv_url": "https://www.meineuhrverkaufen.de/Sell/request",
                    "message": "Accepted for direct purchase.",
                },
                "muv_sell_url": "https://www.meineuhrverkaufen.de/Sell/request",
                "validation_errors": [
                    "MUV_AUTO_SUBMIT is false",
                    "MUV_SELLER_EMAIL is missing",
                ],
            },
        )

        embed = service._build_result_embed(record, result)

        assert embed["title"] == "Rolex Daytona | 116500LN"
        assert embed["url"] == "https://example.com/daytona"
        assert embed["image"]["url"] == "https://example.com/watch.jpg"
        assert "thumbnail" not in embed
        assert embed["footer"]["text"].startswith("Example - Detected:")
        fields = {field["name"]: field["value"] for field in embed["fields"]}
        assert fields["💰 Price:"] == "**€25.000**"
        assert fields["💰 MUV Offer:"] == "**€23.000**"
        assert fields["Spread:"] == "**-€2.000 / -8.0%**"
        assert fields["MUV Link:"] == (
            "[**Open MUV flow**](https://www.meineuhrverkaufen.de/Sell/request)"
        )
        assert "Search similar" in fields["🔍 Chrono24 Search:"]
        assert fields["📦 Box:"] == "**✅**"
        assert fields["📄 Papers:"] == "**✅**"
        assert "116500LN" in embed["title"]
        field_text = "\n".join(
            f"{field['name']}\n{field['value']}" for field in embed["fields"]
        )
        assert "Submit Requirements" not in field_text
        assert "MUV Offer Details" not in field_text
        assert "MUV_AUTO_SUBMIT" not in field_text
    finally:
        store.close()


def test_result_embed_prefers_enriched_result_listing_image(mock_logger, temp_dir):
    store = ActionStore(str(temp_dir / "actions.sqlite3"))
    try:
        action_id = store.save_watch(
            WatchData(
                title="Rolex Daytona",
                url="https://example.com/daytona",
                site_name="Example",
                site_key="example",
                brand="Rolex",
                model="Daytona",
                price=Decimal("25000"),
            )
        )
        record = store.get(action_id)
        service = MUVActionService(None, store, mock_logger)
        result_listing = dict(record.listing)
        result_listing["image_url"] = "https://example.com/enriched-watch.jpg"
        result = MUVResult(
            status="completed",
            title="MUV offer received",
            description="MUV returned an offer for the original listing.",
            data={
                "listing": result_listing,
                "muv_offer": {
                    "price": "23000",
                    "currency": "EUR",
                    "muv_url": "https://www.meineuhrverkaufen.de/Sell/request",
                },
                "muv_sell_url": "https://www.meineuhrverkaufen.de/Sell/request",
            },
        )

        embed = service._build_result_embed(record, result)

        assert embed["image"]["url"] == "https://example.com/enriched-watch.jpg"
    finally:
        store.close()


def test_offer_link_embed_uses_muv_watch_picture_when_no_listing(mock_logger):
    payload = MUVActionService.parse_offer_page(
        _offer_page_html(price=3000),
        "https://www.meineuhrverkaufen.de/Sell/request-1?mt=token",
    )
    service = MUVActionService(None, None, mock_logger)
    result = service._result_for_offer_payload(payload)

    embed = service._build_result_embed(None, result)

    assert embed["title"] == "Breitling Navitimer | A26322"
    assert embed["image"]["url"] == "https://example.com/watch.jpg"
    assert embed["url"] == "https://www.meineuhrverkaufen.de/Sell/request-1?mt=token"
    fields = {field["name"]: field["value"] for field in embed["fields"]}
    assert fields["💰 MUV Offer:"] == "**€3.000**"
    assert fields["MUV Link:"] == (
        "[**Open MUV flow**](https://www.meineuhrverkaufen.de/Sell/request-1?mt=token)"
    )
    assert fields["💰 Price:"] == "**❓**"
    assert any("Chrono24 Search" in field["name"] for field in embed["fields"])


@pytest.mark.asyncio
async def test_result_webhook_dms_requesting_user_for_muv_offer(mock_logger, temp_dir):
    class FakeResponse:
        def __init__(self, status, payload=None):
            self.status = status
            self.payload = payload or {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def json(self):
            return self.payload

        async def text(self):
            return json.dumps(self.payload)

    class FakeSession:
        def __init__(self):
            self.calls = []

        def post(self, url, **kwargs):
            self.calls.append((url, kwargs))
            if url.endswith("/users/@me/channels"):
                return FakeResponse(200, {"id": "dm-channel-1"})
            if url.endswith("/messages"):
                return FakeResponse(201, {"id": "message-1"})
            return FakeResponse(204)

    store = ActionStore(str(temp_dir / "actions.sqlite3"))
    try:
        action_id = store.save_watch(
            WatchData(
                title="Rolex Daytona",
                url="https://example.com/daytona",
                site_name="Example",
                site_key="example",
                brand="Rolex",
                model="Daytona",
                price=Decimal("25000"),
            )
        )
        store.queue_action(action_id, "user-1", "tester", "interaction-1")
        record = store.get(action_id)
        result = MUVResult(
            status="completed",
            title="MUV offer received",
            description="MUV returned an offer.",
            data={
                "listing": record.listing,
                "muv_offer": {
                    "price": "23000",
                    "currency": "EUR",
                    "muv_url": "https://www.meineuhrverkaufen.de/Sell/request",
                },
                "muv_sell_url": "https://www.meineuhrverkaufen.de/Sell/request",
            },
        )
        session = FakeSession()
        service = MUVActionService(session, store, mock_logger)

        with patch("muv_service.APP_CONFIG") as mock_config:
            _configure_muv(mock_config)
            mock_config.muv_result_webhook_url = "https://discord.test/webhook"
            mock_config.muv_dm_results_to_requester = True
            mock_config.discord_bot_token = "bot-token"
            mock_config.discord_api_base_url = "https://discord.test/api"

            await service._send_result_webhook(record, result)

        urls = [url for url, _kwargs in session.calls]
        assert urls == [
            "https://discord.test/webhook",
            "https://discord.test/api/users/@me/channels",
            "https://discord.test/api/channels/dm-channel-1/messages",
        ]
        assert session.calls[1][1]["json"] == {"recipient_id": "user-1"}
        assert session.calls[2][1]["json"]["embeds"][0]["title"] == "Rolex Daytona"
    finally:
        store.close()


@pytest.mark.asyncio
async def test_result_webhook_can_skip_channel_for_requester_dm_only(
    mock_logger, temp_dir
):
    class FakeResponse:
        def __init__(self, status, payload=None):
            self.status = status
            self.payload = payload or {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def json(self):
            return self.payload

        async def text(self):
            return json.dumps(self.payload)

    class FakeSession:
        def __init__(self):
            self.calls = []

        def post(self, url, **kwargs):
            self.calls.append((url, kwargs))
            if url.endswith("/users/@me/channels"):
                return FakeResponse(200, {"id": "dm-channel-1"})
            return FakeResponse(201, {"id": "message-1"})

    store = ActionStore(str(temp_dir / "actions.sqlite3"))
    try:
        action_id = store.save_watch(
            WatchData(
                title="Rolex Daytona",
                url="https://example.com/daytona",
                site_name="Example",
                site_key="example",
                brand="Rolex",
                model="Daytona",
            )
        )
        store.queue_action(action_id, "user-1", "tester", "interaction-1")
        record = store.get(action_id)
        result = MUVResult(
            status="completed",
            title="MUV offer received",
            description="MUV returned an offer.",
            data={
                "listing": record.listing,
                "muv_offer": {"price": "23000", "currency": "EUR"},
            },
        )
        session = FakeSession()
        service = MUVActionService(session, store, mock_logger)

        with patch("muv_service.APP_CONFIG") as mock_config:
            _configure_muv(mock_config)
            mock_config.muv_result_webhook_url = "https://discord.test/webhook"
            mock_config.muv_dm_results_to_requester = True
            mock_config.muv_result_delivery_mode = "dm_only_for_requested"
            mock_config.discord_bot_token = "bot-token"
            mock_config.discord_api_base_url = "https://discord.test/api"

            await service._send_result_webhook(record, result)

        urls = [url for url, _kwargs in session.calls]
        assert urls == [
            "https://discord.test/api/users/@me/channels",
            "https://discord.test/api/channels/dm-channel-1/messages",
        ]
    finally:
        store.close()


def test_should_dm_submitted_result_to_requester(mock_logger, temp_dir):
    store = ActionStore(str(temp_dir / "actions.sqlite3"))
    try:
        action_id = store.save_watch(
            WatchData(
                title="Rolex Daytona",
                url="https://example.com/daytona",
                site_name="Example",
                site_key="example",
                brand="Rolex",
                model="Daytona",
            )
        )
        store.queue_action(action_id, "user-1", "tester", "interaction-1")
        record = store.get(action_id)
        result = MUVResult(
            status="submitted",
            title="MUV request submitted",
            description="Submitted.",
            data={"listing": record.listing},
            submitted=True,
        )

        with patch("muv_service.APP_CONFIG") as mock_config:
            _configure_muv(mock_config)
            mock_config.muv_dm_results_to_requester = True
            mock_config.discord_bot_token = "bot-token"

            assert MUVActionService._should_dm_result(record, result) is True
    finally:
        store.close()


@pytest.mark.asyncio
async def test_result_webhook_does_not_dm_prepared_result(mock_logger, temp_dir):
    store = ActionStore(str(temp_dir / "actions.sqlite3"))
    try:
        action_id = store.save_watch(
            WatchData(
                title="Rolex Daytona",
                url="https://example.com/daytona",
                site_name="Example",
                site_key="example",
                brand="Rolex",
                model="Daytona",
            )
        )
        store.queue_action(action_id, "user-1", "tester", "interaction-1")
        record = store.get(action_id)
        result = MUVResult(
            status="prepared",
            title="MUV request prepared",
            description="Prepared only.",
            data={"listing": record.listing},
        )

        with patch("muv_service.APP_CONFIG") as mock_config:
            _configure_muv(mock_config)
            mock_config.muv_dm_results_to_requester = True
            mock_config.discord_bot_token = "bot-token"

            assert MUVActionService._should_dm_result(record, result) is False
    finally:
        store.close()


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


@pytest.mark.asyncio
async def test_monitor_offer_links_stores_pending_without_notifying(
    mock_logger, temp_dir, monkeypatch
):
    store = ActionStore(str(temp_dir / "actions.sqlite3"))
    try:
        url = "https://www.meineuhrverkaufen.de/Sell/request-1?mt=token"
        store.save_offer_link(url)

        async def fake_fetch_page(_session, _url, _logger):
            return _offer_page_html(price=None, reviewed=False)

        sent = []

        async def fake_send_result_webhook(record, result):
            sent.append((record, result))

        service = MUVActionService(None, store, mock_logger)
        monkeypatch.setattr("muv_service.fetch_page", fake_fetch_page)
        monkeypatch.setattr(service, "_send_result_webhook", fake_send_result_webhook)

        assert await service.monitor_offer_links() == 0

        link = store.list_offer_links()[0]
        assert link.last_fingerprint
        assert link.last_payload["status"] == "pending"
        assert link.last_notified_at is None
        assert sent == []
    finally:
        store.close()
