"""What a watch is worth, and the most to pay for it, from what it is offered for on Chrono24 inside the EU
and what the business itself bought and sold it for."""

import math
import statistics
from datetime import date, timedelta
from decimal import ROUND_FLOOR, Decimal
from typing import Optional, Tuple

from chrono24 import FULL_SET, USED
from config import APP_CONFIG
from prices import Prices

FEWEST = 5  # offers below which the market says too little to go by
# The business's own trades that count: prices change all the time (owner rule, 17 Oct 2026)
TRADED_WITHIN = timedelta(days=90)
MARGIN_TAX = Decimal("0.19")  # VAT on a used watch's margin (Differenzbesteuerung, § 25a UStG)


def ours(prices: Prices, reference: str, kind: str, sold: bool = True,
         brand: Optional[str] = None) -> Tuple[int, Optional[Decimal]]:
    """How many of this kind of the watch the business sold within `TRADED_WITHIN`, or bought if not sold, and the
    middle of their prices: of full sets for a full set (owner rule, 11 Oct 2026: the controlling tool's prices are
    price data)."""
    amounts = prices.traded_for(reference, kind == FULL_SET, date.today() - TRADED_WITHIN, sold, brand)
    return len(amounts), Decimal(str(statistics.median(amounts))) if amounts else None


def worth(prices: Prices, reference: str, kind: str, brand: Optional[str] = None) -> Optional[Decimal]:
    """What this kind of the watch is worth: the lower of what the market asks and what the business sold it for.

    The market: the price a quarter of the Chrono24 offers of this kind inside
    the EU ask less than, from five offers up. Prices below half the middle of
    those read count toward neither the quarter nor the five offers needed.
    A search reads the cheapest 120:
    for a watch offered more than 480 times the dearest of those stands in for
    the quarter, which only lowers it. A full set's market value is at least
    the same watch's used worth. The business: the middle of its own sales of
    the watch within `TRADED_WITHIN`, which still caps its worth.
    """
    found, asked = prices.market(reference, kind)
    if asked:
        cutoff = statistics.median(asked) / 2
        kept = [price for price in asked if price >= cutoff]
        found -= len(asked) - len(kept)
        asked = kept
    market = Decimal(str(asked[min(math.ceil(found / 4), len(asked)) - 1])) if found >= FEWEST and asked else None
    if kind == FULL_SET and market is not None:
        used = worth(prices, reference, USED, brand)
        if used is not None:
            market = max(market, used)
    known = [value for value in (market, ours(prices, reference, kind, brand=brand)[1]) if value is not None]
    return min(known) if known else None


def least_profit(worth: Decimal) -> Decimal:
    """What a watch worth this must at least leave once sold again."""
    return max(worth * Decimal(str(APP_CONFIG.least_profit_share)), Decimal(str(APP_CONFIG.least_profit_eur)))


def most_to_pay(worth: Decimal) -> Decimal:
    """The most to pay for a watch, in whole euros, so that selling it at its worth leaves the least profit.

    Selling costs Chrono24's fee on the price, insured shipping, and the VAT
    on the margin between price and purchase.
    """
    fee = worth * Decimal(str(APP_CONFIG.sale_fee_share))
    shipping = Decimal(str(APP_CONFIG.sale_shipping_eur))
    # worth - fee - shipping - tax * (worth - paid) / (1 + tax) - paid >= least profit, solved for paid
    taxed = MARGIN_TAX / (1 + MARGIN_TAX)
    paid = (worth * (1 - taxed) - fee - shipping - least_profit(worth)) / (1 - taxed)
    return max(paid, Decimal(0)).quantize(Decimal(1), rounding=ROUND_FLOOR)


def buy_limit(prices: Prices, reference: str, kind: str, brand: Optional[str] = None) -> Optional[Decimal]:
    """The most to pay for this kind of a watch: the owner's own buy price, or else the one worked out from its worth,
    no more than the middle of what the business paid for it within `TRADED_WITHIN`."""
    own = prices.buy_price(reference)
    if own is not None:
        return Decimal(str(own))
    return calculated_limit(prices, reference, kind, brand)


def calculated_limit(prices: Prices, reference: str, kind: str, brand: Optional[str] = None) -> Optional[Decimal]:
    """The buy limit worked out from worth and past purchases, independent of the owner's price."""
    value = worth(prices, reference, kind, brand)
    if value is None:
        return None
    paid = ours(prices, reference, kind, sold=False, brand=brand)[1]
    return most_to_pay(value) if paid is None else min(most_to_pay(value), paid)
