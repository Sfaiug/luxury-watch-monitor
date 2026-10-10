"""What the watches the monitor reads are offered for: one row per offer, for as long as it is listed."""

import re
import sqlite3
from datetime import datetime
from typing import Iterable, List, Optional, Tuple

from models import WatchData


def reference_key(reference: str) -> str:
    """A reference as every source writes it alike: "5711/1A-010" and "5711 1a 010" are one watch."""
    return re.sub(r"[^A-Z0-9]", "", reference.upper())


class Prices:
    """The offers seen, in one SQLite file."""

    def __init__(self, path: str):
        self._db = sqlite3.connect(str(path))
        with self._db:
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS offers (
                    site_key TEXT NOT NULL,
                    address TEXT NOT NULL,
                    reference TEXT NOT NULL,
                    price REAL NOT NULL,
                    brand TEXT,
                    model TEXT,
                    year TEXT,
                    condition TEXT,
                    has_box INTEGER,
                    has_papers INTEGER,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    PRIMARY KEY (site_key, address)
                )
            """)
            self._db.execute("CREATE INDEX IF NOT EXISTS offers_reference ON offers (reference)")
            # When the market was last searched for a reference, and how many offers it found
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS searches (
                    reference TEXT PRIMARY KEY,
                    found INTEGER NOT NULL,
                    searched TEXT NOT NULL
                )
            """)

    def close(self):
        self._db.close()

    def saw(self, watches: Iterable[WatchData]):
        """Note that these offers are listed now, at the price they show.

        An offer is known by its shop and its address there. It is kept from the
        sighting that names its reference and a price in euros: most shops name
        the reference only on the offer's own page, which is read once, so a
        later sighting says no more than that the offer still stands, and at
        what price.
        """
        with self._db:
            for watch in watches:
                price = float(watch.price) if watch.price and watch.currency == "EUR" else None
                seen = watch.scraped_at.isoformat(timespec="seconds")
                known = self._db.execute(
                    "UPDATE offers SET last_seen = ?, price = COALESCE(?, price) "
                    "WHERE site_key = ? AND address = ?",
                    (seen, price, watch.site_key, watch.address),
                ).rowcount
                if not known and watch.reference and price:
                    self._db.execute(
                        "INSERT INTO offers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            watch.site_key,
                            watch.address,
                            reference_key(watch.reference),
                            price,
                            watch.brand,
                            watch.model,
                            watch.year,
                            watch.condition,
                            watch.has_box,
                            watch.has_papers,
                            seen,
                            seen,
                        ),
                    )

    def due(self, before: datetime, limit: int) -> List[Tuple[Optional[str], str]]:
        """Brand and reference of offered watches the market was not searched for since `before`, never searched first."""
        return self._db.execute(
            "SELECT MAX(offers.brand), offers.reference FROM offers "
            "LEFT JOIN searches ON searches.reference = offers.reference "
            "WHERE searches.searched IS NULL OR searches.searched < ? "
            "GROUP BY offers.reference "
            "ORDER BY MAX(searches.searched) IS NOT NULL, MAX(searches.searched), offers.reference "
            "LIMIT ?",
            (before.isoformat(timespec="seconds"), limit),
        ).fetchall()

    def searched(self, reference: str, found: int, at: datetime):
        """Note that the market was searched for the reference and found this many offers in all."""
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO searches VALUES (?, ?, ?)",
                (reference_key(reference), found, at.isoformat(timespec="seconds")),
            )

    def market(self, site_key: str, reference: str) -> Tuple[int, List[float]]:
        """How many offers the last search of a market found for a reference, and the prices of those it read and still lists, cheapest first."""
        key = reference_key(reference)
        search = self._db.execute("SELECT found, searched FROM searches WHERE reference = ?", (key,)).fetchone()
        if not search:
            return 0, []
        found, searched = search
        listed = self._db.execute(
            "SELECT price FROM offers WHERE site_key = ? AND reference = ? AND last_seen >= ? ORDER BY price",
            (site_key, key, searched),
        )
        return found, [price for (price,) in listed]
