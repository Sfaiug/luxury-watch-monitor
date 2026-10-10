"""What a watch is worth, and the most to pay for it, from its Chrono24 offers inside the EU."""

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

import chrono24
from config import APP_CONFIG
from models import WatchData
from prices import Prices
from worth import least_profit, most_to_pay, worth

SEARCHED = datetime(2026, 10, 10, 11, 0)
PAGE = (Path(__file__).parent / "pages" / "chrono24.html").read_text(encoding="utf-8")


@pytest.fixture
def prices(tmp_path):
    return Prices(tmp_path / "prices.sqlite3")


def searched(prices, found, offers, at=SEARCHED, reference="116610LN"):
    prices.saw(offers)
    prices.searched(reference, found, at)


def chrono24_offers(*asked, at=SEARCHED, reference="116610LN"):
    return [
        WatchData(
            title="Rolex Submariner Date",
            url=f"https://www.chrono24.de/rolex/submariner--id{n}.htm",
            site_name="Chrono24",
            site_key="chrono24",
            reference=reference,
            price=Decimal(price),
            scraped_at=at,
        )
        for n, price in enumerate(asked)
    ]


def test_a_watch_is_worth_what_a_quarter_of_its_eu_offers_ask_less_than(prices):
    found, offers = chrono24.read(PAGE, "Rolex", "116610LN", SEARCHED)
    searched(prices, found, offers)

    # 192 offers in all: the 48th cheapest
    assert worth(prices, "116610LN") == Decimal("10800")
    assert worth(prices, "116610 ln") == Decimal("10800")


def test_fewer_than_five_offers_say_too_little(prices):
    searched(prices, 4, chrono24_offers("9000", "9500", "9800", "12000"))
    assert worth(prices, "116610LN") is None

    searched(prices, 5, chrono24_offers("9000", "9500", "9800", "12000", "12500"))
    assert worth(prices, "116610LN") == Decimal("9500")


def test_a_watch_never_searched_has_no_worth(prices):
    assert worth(prices, "116610LN") is None


def test_beyond_the_page_the_dearest_offer_read_stands_in_for_the_quarter(prices):
    searched(prices, 1000, chrono24_offers(*(str(9000 + n) for n in range(120))))
    assert worth(prices, "116610LN") == Decimal("9119")


def test_only_the_offers_its_last_search_still_found_count(prices):
    gone = chrono24_offers("5000", at=SEARCHED - timedelta(days=8))
    gone[0].url = "https://www.chrono24.de/rolex/sold--id1.htm"
    searched(prices, 6, gone, at=SEARCHED - timedelta(days=8))
    searched(prices, 5, chrono24_offers("9000", "9500", "9800", "12000", "12500"))

    assert worth(prices, "116610LN") == Decimal("9500")


def test_a_shop_s_offers_are_not_the_market(prices):
    shop = chrono24_offers("5000", "5100", "5200", "5300", "5400")
    for offer in shop:
        offer.site_key = "worldoftime"
    searched(prices, 5, shop + chrono24_offers("9000", "9500", "9800", "12000", "12500"))

    assert worth(prices, "116610LN") == Decimal("9500")


def test_the_least_profit_is_a_tenth_of_the_worth_and_never_under_500_euros():
    assert least_profit(Decimal("10000")) == Decimal("1000")
    assert least_profit(Decimal("3000")) == Decimal("500")


@pytest.mark.parametrize("value", ["1500", "3000", "10000", "25000", "80000"])
def test_paying_the_most_leaves_the_least_profit_after_selling_costs_and_margin_tax(value):
    value = Decimal(value)
    paid = most_to_pay(value)

    fee = value * Decimal(str(APP_CONFIG.sale_fee_share))
    shipping = Decimal(str(APP_CONFIG.sale_shipping_eur))
    margin_tax = (value - paid) * Decimal("0.19") / Decimal("1.19")
    profit = value - fee - shipping - margin_tax - paid

    assert least_profit(value) <= profit < least_profit(value) + 1
    assert paid == paid.to_integral_value()


def test_the_owner_moves_the_least_profit(monkeypatch):
    monkeypatch.setattr(APP_CONFIG, "least_profit_share", 0.15)
    monkeypatch.setattr(APP_CONFIG, "least_profit_eur", 800)

    assert least_profit(Decimal("10000")) == Decimal("1500")
    assert least_profit(Decimal("4000")) == Decimal("800")
    assert most_to_pay(Decimal("10000")) == Decimal("7370")


def test_a_watch_too_cheap_to_leave_the_least_profit_is_worth_buying_at_no_price():
    assert most_to_pay(Decimal("400")) == Decimal("0")
