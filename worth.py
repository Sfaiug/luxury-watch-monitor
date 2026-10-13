"""What a watch is worth, and the most to pay for it, from what it is offered for on Chrono24 inside the EU
and what the business itself bought and sold it for."""

import math
import statistics
from datetime import date, timedelta
from decimal import ROUND_FLOOR, Decimal
from typing import Optional, Tuple

from chrono24 import FULL_SET
from config import APP_CONFIG
from prices import Prices

FEWEST = 5  # offers below which the market says too little to go by
TRADED_WITHIN = timedelta(days=365)  # the business's own trades that count, prices changing as they do
MARGIN_TAX = Decimal("0.19")  # VAT on a used watch's margin (Differenzbesteuerung, § 25a UStG)
SHIPPED = 0.95  # the share of the business's own buys, the cheapest, too small a deal to be fetched in person


def ours(prices: Prices, reference: str, kind: str, sold: bool = True) -> Tuple[int, Optional[Decimal]]:
    """How many of this kind of the watch the business sold within the last year, or bought if not sold, and the
    middle of their prices: of full sets for a full set (owner rule, 11 Oct 2026: the controlling tool's prices are
    price data)."""
    amounts = prices.traded_for(reference, kind == FULL_SET, date.today() - TRADED_WITHIN, sold)
    return len(amounts), Decimal(str(statistics.median(amounts))) if amounts else None


def worth(prices: Prices, reference: str, kind: str) -> Optional[Decimal]:
    """What this kind of the watch is worth: the lower of what the market asks and what the business sold it for.

    The market: the price a quarter of the Chrono24 offers of this kind inside
    the EU ask less than, from five offers up. A search reads the cheapest 120:
    for a watch offered more than 480 times the dearest of those stands in for
    the quarter, which only lowers it. The business: the middle of its own
    sales of the watch within the last year.
    """
    found, asked = prices.market(reference, kind)
    market = Decimal(str(asked[min(math.ceil(found / 4), len(asked)) - 1])) if found >= FEWEST and asked else None
    known = [value for value in (market, ours(prices, reference, kind)[1]) if value is not None]
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


def fetched(prices: Prices, limit: Decimal) -> bool:
    """Whether a watch the agent pays at most this much for is a deal big enough to be fetched in person: as dear as
    the dearest twentieth of what the business bought within the last year (owner rule, 13 Oct 2026: "it should be
    95% delivery of the time. I dont really want to have to pickup unless its big deals"). With none known, it is
    shipped."""
    paid = prices.paid_since(date.today() - TRADED_WITHIN)
    return bool(paid) and limit >= Decimal(str(paid[int(len(paid) * SHIPPED)]))


def buy_limit(prices: Prices, reference: str, kind: str) -> Optional[Decimal]:
    """The most to pay for this kind of a watch: the owner's own buy price, or else the one worked out from its worth,
    no more than the middle of what the business paid for it within the last year."""
    own = prices.buy_price(reference)
    if own is not None:
        return Decimal(str(own))
    value = worth(prices, reference, kind)
    if value is None:
        return None
    paid = ours(prices, reference, kind, sold=False)[1]
    return most_to_pay(value) if paid is None else min(most_to_pay(value), paid)
