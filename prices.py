"""What the watches the monitor reads are offered for: one row per offer, for as long as it is listed."""

import re
import sqlite3
from datetime import date, datetime
from typing import Iterable, List, Optional, Sequence, Tuple

from models import WatchData, normalize_brand


def reference_key(reference: str) -> str:
    """A reference as every source writes it alike: "5711/1A-010" and "5711 1a 010" are one watch."""
    return re.sub(r"[^A-Z0-9]", "", reference.upper())


def brand_key(brand: Optional[str]) -> str:
    """A brand alike across the export and offers, without spacing differences."""
    return normalize_brand(brand).replace(" ", "")


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
            # The owner's own buy price for a reference, in place of the one worked out
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS buy_prices (
                    reference TEXT PRIMARY KEY,
                    price REAL NOT NULL,
                    set_at TEXT NOT NULL
                )
            """)
            # What the business itself bought and sold watches for, from the owner's controlling tool
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    reference TEXT NOT NULL,
                    full_set INTEGER NOT NULL,
                    bought TEXT,
                    paid REAL,
                    sold TEXT,
                    sold_for REAL,
                    brand TEXT
                )
            """)
            if "brand" not in {column[1] for column in self._db.execute("PRAGMA table_info(trades)")}:
                self._db.execute("ALTER TABLE trades ADD COLUMN brand TEXT")
            self._db.execute("CREATE INDEX IF NOT EXISTS trades_reference ON trades (reference)")
            self._db.execute("CREATE TABLE IF NOT EXISTS controlling_warning (sent INTEGER PRIMARY KEY CHECK (sent = 1))")
            # Searches made before they asked for one kind of watch held new ones too: they count as none
            if self._db.execute("PRAGMA user_version").fetchone()[0] < 2:
                self._db.execute("DROP TABLE IF EXISTS searches")
                self._db.execute("DROP TABLE IF EXISTS searched_offers")
                self._db.execute("PRAGMA user_version = 2")
            # When the market was last searched for one kind of a reference's watches, and how many offers it found
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS searches (
                    reference TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    found INTEGER NOT NULL,
                    searched TEXT NOT NULL,
                    PRIMARY KEY (reference, kind)
                )
            """)
            # The offers that search read
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS searched_offers (
                    reference TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    site_key TEXT NOT NULL,
                    address TEXT NOT NULL,
                    PRIMARY KEY (reference, kind, site_key, address)
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

    def due(self, kinds: Sequence[str], before: datetime, limit: int) -> List[Tuple[Optional[str], str, str]]:
        """Brand, reference and kind of offered watches the market was not searched for since `before`: first the ones
        never searched or offered anew since, the latest offered first, then the ones searched longest ago."""
        each = " UNION ALL ".join("SELECT ? AS kind, ? AS rank" for _ in kinds)
        # The market's own offers, from the site its searches read, come with the searches: offered anew they are not
        offered = "MAX(CASE WHEN offers.site_key NOT IN (SELECT site_key FROM searched_offers) THEN offers.first_seen END)"
        last = f"CASE WHEN {offered} > MAX(searches.searched) THEN NULL ELSE MAX(searches.searched) END"
        return self._db.execute(
            f"SELECT MAX(offers.brand), offers.reference, kinds.kind FROM offers CROSS JOIN ({each}) AS kinds "
            "LEFT JOIN searches ON searches.reference = offers.reference AND searches.kind = kinds.kind "
            "WHERE searches.searched IS NULL OR searches.searched < ? "
            "GROUP BY offers.reference, kinds.kind "
            f"ORDER BY {last} IS NOT NULL, {last}, {offered} DESC, offers.reference, kinds.rank "
            "LIMIT ?",
            (*[value for rank, kind in enumerate(kinds) for value in (kind, rank)], before.isoformat(timespec="seconds"), limit),
        ).fetchall()

    def searched(self, reference: str, kind: str, found: int, offers: List[WatchData], at: datetime):
        """Note that the market was searched for this kind of the reference's watches, found this many offers in all and read these."""
        key = reference_key(reference)
        self.saw(offers)
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO searches VALUES (?, ?, ?, ?)",
                (key, kind, found, at.isoformat(timespec="seconds")),
            )
            self._db.execute("DELETE FROM searched_offers WHERE reference = ? AND kind = ?", (key, kind))
            self._db.executemany(
                "INSERT OR IGNORE INTO searched_offers VALUES (?, ?, ?, ?)",
                [(key, kind, offer.site_key, offer.address) for offer in offers],
            )

    def ever_searched(self, reference: str, kind: str) -> bool:
        """Whether the market was ever searched for this kind of the reference's watches."""
        key = reference_key(reference)
        return self._db.execute("SELECT 1 FROM searches WHERE reference = ? AND kind = ?", (key, kind)).fetchone() is not None

    def market(self, reference: str, kind: str, since: datetime = datetime.min) -> Tuple[int, List[float]]:
        """How many offers of this kind the last search of the market found for a reference, and the prices of those it read, cheapest first:
        none where that search was made before `since`."""
        key = reference_key(reference)
        search = self._db.execute(
            "SELECT found FROM searches WHERE reference = ? AND kind = ? AND searched >= ?",
            (key, kind, since.isoformat(timespec="seconds")),
        ).fetchone()
        if not search:
            return 0, []
        read = self._db.execute(
            "SELECT price FROM searched_offers JOIN offers USING (site_key, address) "
            "WHERE searched_offers.reference = ? AND searched_offers.kind = ? ORDER BY price",
            (key, kind),
        )
        return search[0], [price for (price,) in read]

    def references(self) -> List[Tuple[str, Optional[str], Optional[str], Optional[str]]]:
        """Every reference offered: its brand and model, and when the market was last searched for it."""
        return self._db.execute(
            "SELECT offers.reference, MAX(offers.brand), MAX(offers.model), MAX(searches.searched) "
            "FROM offers LEFT JOIN searches ON searches.reference = offers.reference "
            "GROUP BY offers.reference ORDER BY MAX(offers.brand) IS NULL, MAX(offers.brand), offers.reference"
        ).fetchall()

    def trade_counts(self) -> Tuple[int, int]:
        """How many stored purchases and sales have both a day and an amount."""
        return self._db.execute(
            "SELECT COUNT(CASE WHEN bought IS NOT NULL AND paid IS NOT NULL THEN 1 END), "
            "COUNT(CASE WHEN sold IS NOT NULL AND sold_for IS NOT NULL THEN 1 END) FROM trades"
        ).fetchone()

    @property
    def trades_warned(self) -> bool:
        """Whether the owner heard of the unreadable export, until readable trades arrive."""
        return self._db.execute("SELECT 1 FROM controlling_warning").fetchone() is not None

    def warned_about_trades(self):
        with self._db:
            self._db.execute("INSERT OR IGNORE INTO controlling_warning VALUES (1)")

    def traded(self, trades: Iterable):
        """Keep these trades, the controlling tool's latest export, in place of the ones kept before."""
        with self._db:
            self._db.execute("DELETE FROM trades")
            self._db.executemany(
                "INSERT INTO trades VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (t.reference, t.full_set, t.bought and t.bought.isoformat(), t.paid and float(t.paid),
                     t.sold and t.sold.isoformat(), t.sold_for and float(t.sold_for), brand_key(t.brand))
                    for t in trades
                ],
            )
            self._db.execute("DELETE FROM controlling_warning")

    def traded_for(self, reference: str, full_sets_only: bool, since: date, sold: bool,
                   brand: Optional[str] = None) -> List[float]:
        """What the business sold the watch for since that day, or paid for it if not sold, the full sets only if asked,
        cheapest first. Where the watch's brand is known, only its brand's trades count."""
        day, amount = ("sold", "sold_for") if sold else ("bought", "paid")
        brand = brand_key(brand)
        return [
            price
            for (price,) in self._db.execute(
                f"SELECT {amount} FROM trades WHERE reference = ? AND {day} >= ? AND {amount} IS NOT NULL "
                f"AND (full_set OR NOT ?) AND (? = '' OR brand = ?) ORDER BY {amount}",
                (reference_key(reference), since.isoformat(), full_sets_only, brand, brand),
            )
        ]

    def buy_price(self, reference: str) -> Optional[float]:
        """The owner's own buy price for a reference, if they set one."""
        row = self._db.execute("SELECT price FROM buy_prices WHERE reference = ?", (reference_key(reference),)).fetchone()
        return row[0] if row else None

    def set_buy_price(self, reference: str, price: Optional[float], at: datetime):
        """Set the owner's buy price for a reference; None takes it away."""
        with self._db:
            if price is None:
                self._db.execute("DELETE FROM buy_prices WHERE reference = ?", (reference_key(reference),))
            else:
                self._db.execute(
                    "INSERT OR REPLACE INTO buy_prices VALUES (?, ?, ?)",
                    (reference_key(reference), price, at.isoformat(timespec="seconds")),
                )
