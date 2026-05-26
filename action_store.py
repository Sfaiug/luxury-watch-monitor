"""Persistent storage for Discord-triggered MUV actions."""

import hashlib
import hmac
import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from models import WatchData


def _utcnow() -> str:
    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


@dataclass
class ActionRecord:
    """Stored listing/action state for a MUV button."""

    action_id: str
    status: str
    listing: Dict[str, Any]
    result: Dict[str, Any]
    requested_by: Optional[str] = None
    requested_by_name: Optional[str] = None
    interaction_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    submitted_at: Optional[str] = None
    last_error: Optional[str] = None


@dataclass
class OfferLinkRecord:
    """Stored MUV offer-link polling state."""

    url: str
    action_id: Optional[str]
    last_fingerprint: Optional[str]
    last_payload: Dict[str, Any]
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    last_notified_at: Optional[str] = None


class ActionStore:
    """SQLite-backed store for listings and MUV action state."""

    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._initialize()

    def close(self):
        with self._lock:
            self._conn.close()

    def _initialize(self):
        with self._lock:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS muv_actions (
                    action_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    listing_json TEXT NOT NULL,
                    result_json TEXT,
                    requested_by TEXT,
                    requested_by_name TEXT,
                    interaction_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    submitted_at TEXT,
                    last_error TEXT
                )
                """)
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS muv_offer_links (
                    url TEXT PRIMARY KEY,
                    action_id TEXT,
                    last_fingerprint TEXT,
                    last_payload_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_notified_at TEXT
                )
                """)
            self._conn.commit()

    def save_watch(self, watch: WatchData) -> str:
        """Persist a notified listing and return its stable action id."""
        action_id = self.action_id_for_watch(watch)
        now = _utcnow()
        listing = self._watch_to_dict(watch)

        with self._lock:
            self._conn.execute(
                """
                INSERT INTO muv_actions (
                    action_id, status, listing_json, result_json, created_at, updated_at
                )
                VALUES (?, 'not_requested', ?, '{}', ?, ?)
                ON CONFLICT(action_id) DO UPDATE SET
                    listing_json=excluded.listing_json,
                    updated_at=excluded.updated_at
                """,
                (action_id, json.dumps(listing, ensure_ascii=False), now, now),
            )
            self._conn.commit()

        return action_id

    def get(self, action_id: str) -> Optional[ActionRecord]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM muv_actions WHERE action_id = ?",
                (action_id,),
            ).fetchone()

        return self._row_to_record(row) if row else None

    def queue_action(
        self,
        action_id: str,
        requested_by: Optional[str],
        requested_by_name: Optional[str],
        interaction_id: Optional[str],
    ) -> Tuple[bool, Optional[ActionRecord]]:
        """Mark an action queued unless it is already in-flight or submitted."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM muv_actions WHERE action_id = ?",
                (action_id,),
            ).fetchone()
            if not row:
                return False, None

            current = row["status"]
            if current in {"queued", "running", "submitted", "completed"}:
                return False, self._row_to_record(row)

            now = _utcnow()
            self._conn.execute(
                """
                UPDATE muv_actions
                SET status='queued',
                    requested_by=?,
                    requested_by_name=?,
                    interaction_id=?,
                    updated_at=?,
                    last_error=NULL
                WHERE action_id=?
                """,
                (requested_by, requested_by_name, interaction_id, now, action_id),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM muv_actions WHERE action_id = ?",
                (action_id,),
            ).fetchone()

        return True, self._row_to_record(row)

    def update_status(
        self,
        action_id: str,
        status: str,
        *,
        result: Optional[Dict[str, Any]] = None,
        last_error: Optional[str] = None,
        submitted: bool = False,
    ):
        now = _utcnow()
        result_json = json.dumps(result or {}, ensure_ascii=False)
        submitted_at = now if submitted else None

        with self._lock:
            if submitted:
                self._conn.execute(
                    """
                    UPDATE muv_actions
                    SET status=?, result_json=?, last_error=?, submitted_at=?, updated_at=?
                    WHERE action_id=?
                    """,
                    (status, result_json, last_error, submitted_at, now, action_id),
                )
            else:
                self._conn.execute(
                    """
                    UPDATE muv_actions
                    SET status=?, result_json=?, last_error=?, updated_at=?
                    WHERE action_id=?
                    """,
                    (status, result_json, last_error, now, action_id),
                )
            self._conn.commit()

    def save_offer_link(self, url: str, action_id: Optional[str] = None):
        """Track a MUV offer URL for polling without duplicating rows."""
        if not url:
            return

        now = _utcnow()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO muv_offer_links (
                    url, action_id, last_payload_json, created_at, updated_at
                )
                VALUES (?, ?, '{}', ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    action_id=COALESCE(excluded.action_id, muv_offer_links.action_id),
                    updated_at=excluded.updated_at
                """,
                (url, action_id, now, now),
            )
            self._conn.commit()

    def list_offer_links(self) -> List[OfferLinkRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM muv_offer_links ORDER BY created_at ASC"
            ).fetchall()

        return [self._row_to_offer_link(row) for row in rows]

    def update_offer_link_state(
        self,
        url: str,
        fingerprint: str,
        payload: Dict[str, Any],
        *,
        notified: bool,
    ):
        now = _utcnow()
        last_notified_at = now if notified else None
        payload_json = json.dumps(payload or {}, ensure_ascii=False)

        with self._lock:
            if notified:
                self._conn.execute(
                    """
                    UPDATE muv_offer_links
                    SET last_fingerprint=?,
                        last_payload_json=?,
                        updated_at=?,
                        last_notified_at=?
                    WHERE url=?
                    """,
                    (fingerprint, payload_json, now, last_notified_at, url),
                )
            else:
                self._conn.execute(
                    """
                    UPDATE muv_offer_links
                    SET last_fingerprint=?,
                        last_payload_json=?,
                        updated_at=?
                    WHERE url=?
                    """,
                    (fingerprint, payload_json, now, url),
                )
            self._conn.commit()

    @staticmethod
    def action_id_for_watch(watch: WatchData) -> str:
        source = f"{watch.site_key}|{watch.composite_id}|{watch.url}"
        return hashlib.sha256(source.encode("utf-8")).hexdigest()[:32]

    @staticmethod
    def custom_id(action_id: str, secret: str = "") -> str:
        if not secret:
            return f"muv:{action_id}"
        signature = hmac.new(
            secret.encode("utf-8"), action_id.encode("utf-8"), hashlib.sha256
        )
        return f"muv:{action_id}:{signature.hexdigest()[:16]}"

    @staticmethod
    def parse_custom_id(custom_id: str, secret: str = "") -> Optional[str]:
        if not custom_id.startswith("muv:"):
            return None
        parts = custom_id.split(":")
        action_id = parts[1].strip() if len(parts) >= 2 else ""
        if secret:
            if len(parts) != 3:
                return None
            expected = ActionStore.custom_id(action_id, secret).split(":")[2]
            if not hmac.compare_digest(parts[2], expected):
                return None
        return action_id or None

    @staticmethod
    def _watch_to_dict(watch: WatchData) -> Dict[str, Any]:
        def clean(value):
            if isinstance(value, Decimal):
                return str(value)
            if isinstance(value, datetime):
                return value.isoformat()
            return value

        return {
            "title": watch.title,
            "url": watch.url,
            "site_name": watch.site_name,
            "site_key": watch.site_key,
            "brand": watch.brand,
            "model": watch.model,
            "reference": watch.reference,
            "year": watch.year,
            "price": clean(watch.price),
            "currency": watch.currency,
            "price_display": watch.price_display,
            "image_url": watch.image_url,
            "image_urls": [watch.image_url] if watch.image_url else [],
            "condition": watch.condition,
            "has_papers": watch.has_papers,
            "has_box": watch.has_box,
            "case_material": watch.case_material,
            "diameter": watch.diameter,
            "scraped_at": clean(watch.scraped_at),
            "composite_id": watch.composite_id,
        }

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> ActionRecord:
        return ActionRecord(
            action_id=row["action_id"],
            status=row["status"],
            listing=json.loads(row["listing_json"]),
            result=json.loads(row["result_json"] or "{}"),
            requested_by=row["requested_by"],
            requested_by_name=row["requested_by_name"],
            interaction_id=row["interaction_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            submitted_at=row["submitted_at"],
            last_error=row["last_error"],
        )

    @staticmethod
    def _row_to_offer_link(row: sqlite3.Row) -> OfferLinkRecord:
        return OfferLinkRecord(
            url=row["url"],
            action_id=row["action_id"],
            last_fingerprint=row["last_fingerprint"],
            last_payload=json.loads(row["last_payload_json"] or "{}"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_notified_at=row["last_notified_at"],
        )
