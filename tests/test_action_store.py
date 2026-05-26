"""Tests for MUV action persistence."""

from decimal import Decimal

from action_store import ActionStore
from models import WatchData


def test_save_watch_and_get_record(temp_dir):
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
        )

        action_id = store.save_watch(watch)
        record = store.get(action_id)

        assert record is not None
        assert record.status == "not_requested"
        assert record.listing["title"] == "Rolex Daytona 116500LN"
        assert record.listing["price"] == "25000"
        assert record.listing["image_urls"] == ["https://example.com/watch.jpg"]
    finally:
        store.close()


def test_queue_action_is_idempotent(temp_dir):
    store = ActionStore(str(temp_dir / "actions.sqlite3"))
    try:
        watch = WatchData(
            title="Omega Speedmaster",
            url="https://example.com/speedmaster",
            site_name="Example",
            site_key="example",
        )
        action_id = store.save_watch(watch)

        queued, record = store.queue_action(action_id, "123", "Dillon", "interaction-1")
        duplicate, duplicate_record = store.queue_action(
            action_id, "123", "Dillon", "interaction-2"
        )

        assert queued is True
        assert record.status == "queued"
        assert duplicate is False
        assert duplicate_record.status == "queued"
    finally:
        store.close()


def test_update_status_records_result_and_error(temp_dir):
    store = ActionStore(str(temp_dir / "actions.sqlite3"))
    try:
        watch = WatchData(
            title="Cartier Tank",
            url="https://example.com/tank",
            site_name="Example",
            site_key="example",
        )
        action_id = store.save_watch(watch)

        store.update_status(
            action_id,
            "failed",
            result={"reason": "missing image"},
            last_error="missing image",
        )
        record = store.get(action_id)

        assert record.status == "failed"
        assert record.result == {"reason": "missing image"}
        assert record.last_error == "missing image"
    finally:
        store.close()


def test_custom_id_signature_round_trip():
    action_id = "abc123"
    custom_id = ActionStore.custom_id(action_id, "secret")

    assert ActionStore.parse_custom_id(custom_id, "secret") == action_id
    assert ActionStore.parse_custom_id(custom_id, "wrong") is None
    assert ActionStore.parse_custom_id("muv:abc123", "secret") is None
