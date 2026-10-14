"""What the business itself bought and sold watches for: the owner's controlling tool, in the export the owner sends
by hand (owner rules, 11 Oct 2026). It stays on the server, out of git, for it names sellers: of each row only the
reference, brand, box and papers, and the purchase and the sale with their days are read."""

import csv
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import List, Optional

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
    try:
        amount = Decimal(re.sub(r"[^\d,-]", "", text or "").replace(",", "."))
    except InvalidOperation:
        return None
    return amount if amount > 0 else None


def _marked(text: str) -> bool:
    # "x (Extract)" papers are the maker's extract, not the original papers
    return text.strip().lower() == "x"


def read(path: str) -> List[Trade]:
    """The trades in the controlling tool's export of its "Uhren" sheet, as CSV."""
    with open(path, encoding="utf-8-sig", newline="") as export:
        return [
            Trade(
                reference=reference_key(row["Referenznummer"]),
                full_set=_marked(row["Box"]) and _marked(row["Papiere"]),
                bought=_day(row["Ankaufdatum"]),
                paid=_euros(row["EK"]),
                sold=_day(row["Verkaufsdatum"]),
                sold_for=_euros(row["VK realisiert"]),
                brand=row["Marke"],
            )
            for row in csv.DictReader(export)
            if reference_key(row["Referenznummer"] or "")
        ]
