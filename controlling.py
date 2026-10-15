"""What the business itself bought and sold watches for: the owner's controlling tool, in the export the owner sends
by hand (owner rules, 11 Oct 2026). It stays on the server, out of git, for it names sellers: of each row only the
reference, brand, box and papers, and the purchase and the sale with their days are read."""

import csv
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional, Tuple

from prices import reference_key


@dataclass(frozen=True)
class Trade:
    reference: str
    full_set: bool  # with the original box and papers both
    bought: Optional[date]
    paid: Optional[Decimal]
    sold: Optional[date]
    sold_for: Optional[Decimal]
    brand: str = ""


def _day(text: str) -> Optional[date]:
    try:
        return datetime.strptime(text.strip(), "%d.%m.%Y").date()
    except ValueError:
        return None


def _euros(text: str) -> Optional[Decimal]:
    # "€4.125,000" and "1.450,00 €": dots between the thousands, a comma before the cents
    match = re.fullmatch(r"€?\s*(-?(?:\d+|\d{1,3}(?:\.\d{3})+)(?:,\d+)?)\s*€?", (text or "").strip())
    if not match:
        return None
    amount = Decimal(match[1].replace(".", "").replace(",", "."))
    return amount if amount > 0 else None


def _marked(text: str) -> bool:
    # "x (Extract)" papers are the maker's extract, not the original papers
    return text.strip().lower() == "x"


def read(path: str, previous: Tuple[int, int] = (0, 0)) -> List[Trade]:
    """Read the export, retaining at least 90% of the previous export's dated purchases and sales."""
    columns = {"Referenznummer", "Box", "Papiere", "Ankaufdatum", "EK", "Verkaufsdatum", "VK realisiert", "Marke"}
    trades = []
    try:
        with open(path, encoding="utf-8-sig", newline="") as export:
            rows = csv.DictReader(export, strict=True)
            missing = columns - set(rows.fieldnames or [])
            if missing:
                raise ValueError("Missing CSV columns: " + ", ".join(sorted(missing)) + ". Use a comma-separated export.")
            for row in rows:
                if None in row or any(row[column] is None for column in columns):
                    raise ValueError(f"CSV row {rows.line_num} has the wrong number of columns.")
                reference = reference_key(row["Referenznummer"])
                if not reference:
                    continue
                trades.append(Trade(
                    reference=reference,
                    full_set=_marked(row["Box"]) and _marked(row["Papiere"]),
                    bought=_day(row["Ankaufdatum"]),
                    paid=_euros(row["EK"]),
                    sold=_day(row["Verkaufsdatum"]),
                    sold_for=_euros(row["VK realisiert"]),
                    brand=row["Marke"],
                ))
    except UnicodeError:
        raise ValueError("The CSV must be encoded as UTF-8.") from None
    except csv.Error:
        raise ValueError("The CSV has invalid quoting or separators.") from None

    counts = (sum(t.bought is not None and t.paid is not None for t in trades),
              sum(t.sold is not None and t.sold_for is not None for t in trades))
    if not any(counts) or any(current < old * 0.9 for current, old in zip(counts, previous)):
        raise ValueError(
            f"Readable purchases: {counts[0]} (previous export: {previous[0]}); "
            f"readable sales: {counts[1]} (previous export: {previous[1]}). "
            "Dates must use DD.MM.YYYY and amounts German separators, e.g. 1.000,00."
        )
    return trades
