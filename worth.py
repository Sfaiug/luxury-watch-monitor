"""What a watch is worth, and the most to pay for it, from what it is offered for on Chrono24 inside the EU."""

import math
from decimal import ROUND_FLOOR, Decimal
from typing import Optional

from config import APP_CONFIG
from prices import Prices

FEWEST = 5  # offers below which the market says too little to go by
MARGIN_TAX = Decimal("0.19")  # VAT on a used watch's margin (Differenzbesteuerung, § 25a UStG)


def worth(prices: Prices, reference: str) -> Optional[Decimal]:
    """The price a quarter of the watch's Chrono24 offers inside the EU ask less than; None from fewer than five.

    A search reads the cheapest 120 offers: for a watch offered more than 480
    times the dearest of those stands in for the quarter, which only lowers it.
    """
    found, asked = prices.market("chrono24", reference)
    if found < FEWEST or not asked:
        return None
    return Decimal(str(asked[min(math.ceil(found / 4), len(asked)) - 1]))


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
