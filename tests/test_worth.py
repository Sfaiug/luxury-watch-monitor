"""What a watch is worth, and the most to pay for it, from its Chrono24 offers inside the EU."""

import csv
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import chrono24
import controlling
from agent import Reading, decide
from chrono24 import FULL_SET, USED
from config import APP_CONFIG
from models import WatchData
from prices import Prices
from prices_page import PATH, PricesPage, key
from worth import buy_limit, least_profit, most_to_pay, ours, worth

SEARCHED = datetime(2026, 10, 10, 11, 0)
PAGE = (Path(__file__).parent / "pages" / "chrono24.html").read_text(encoding="utf-8")


@pytest.fixture
def prices(tmp_path):
    return Prices(tmp_path / "prices.sqlite3")


def searched(prices, found, offers, at=SEARCHED, reference="116610LN", kind=USED):
    prices.searched(reference, kind, found, offers, at)


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
    assert worth(prices, "116610LN", USED) == Decimal("10800")
    assert worth(prices, "116610 ln", USED) == Decimal("10800")


def test_a_full_set_is_worth_what_a_quarter_of_the_full_sets_ask_less_than(prices):
    searched(prices, 8, chrono24_offers(*(str(9000 + 100 * n) for n in range(8))))
    full_sets = chrono24_offers("9600", "9700", "9800", "9900", "10500")
    for offer in full_sets:
        offer.url = offer.url.replace("--id", "-full-set--id")
    searched(prices, 5, full_sets, kind=FULL_SET)

    assert worth(prices, "116610LN", USED) == Decimal("9100")
    assert worth(prices, "116610LN", FULL_SET) == Decimal("9700")


def test_fewer_than_five_offers_say_too_little(prices):
    searched(prices, 4, chrono24_offers("9000", "9500", "9800", "12000"))
    assert worth(prices, "116610LN", USED) is None

    searched(prices, 5, chrono24_offers("9000", "9500", "9800", "12000", "12500"))
    assert worth(prices, "116610LN", USED) == Decimal("9500")


def test_a_watch_never_searched_has_no_worth(prices):
    assert worth(prices, "116610LN", USED) is None


def test_beyond_the_page_the_dearest_offer_read_stands_in_for_the_quarter(prices):
    searched(prices, 1000, chrono24_offers(*(str(9000 + n) for n in range(120))))
    assert worth(prices, "116610LN", USED) == Decimal("9119")


def test_only_the_offers_its_last_search_still_found_count(prices):
    gone = chrono24_offers("5000", at=SEARCHED - timedelta(days=8))
    gone[0].url = "https://www.chrono24.de/rolex/sold--id1.htm"
    searched(prices, 6, gone, at=SEARCHED - timedelta(days=8))
    searched(prices, 5, chrono24_offers("9000", "9500", "9800", "12000", "12500"))

    assert worth(prices, "116610LN", USED) == Decimal("9500")


def test_the_offers_a_search_read_count_whichever_reference_read_them_first(prices):
    earlier = SEARCHED - timedelta(hours=1)
    searched(prices, 4, chrono24_offers("9000", "9100", "9200", "9300", at=earlier), at=earlier, reference="116610")
    searched(prices, 8, chrono24_offers(*(str(9000 + 100 * n) for n in range(8))))

    assert worth(prices, "116610LN", USED) == Decimal("9100")
    assert prices.market("116610", USED) == (4, [9000, 9100, 9200, 9300])


def test_a_shop_s_offers_are_not_the_market(prices):
    shop = chrono24_offers("5000", "5100", "5200", "5300", "5400")
    for offer in shop:
        offer.site_key = "worldoftime"
    prices.saw(shop)
    searched(prices, 5, chrono24_offers("9000", "9500", "9800", "12000", "12500"))

    assert worth(prices, "116610LN", USED) == Decimal("9500")


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


@pytest.fixture
def trades(prices, tmp_path):
    """Synthetic exports for brands that share reference 3800."""
    def keep(*extra, full_set=True):
        path = tmp_path / "controlling.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as export:
            writer = csv.writer(export)
            writer.writerow(["Marke", "Referenznummer", "Box", "Papiere", "Ankaufdatum", "EK",
                             "Verkaufsdatum", "VK realisiert"])
            for brand, complete, paid, sold_for in [
                ("Patek Philipp", full_set, "35000", "42000"),
                ("Patek Philippe ", full_set, "39000", "51500"),
                *extra,
            ]:
                writer.writerow([brand, "38 00", "x" if complete else "", "x" if complete else "",
                                 date.today().strftime("%d.%m.%Y"), paid,
                                 date.today().strftime("%d.%m.%Y"), sold_for])
        prices.traded(controlling.read(path))
    return keep


@pytest.mark.parametrize("kind", [USED, FULL_SET])
@pytest.mark.parametrize("brand", ["Patek Philippe", "Patek Philipp", " pAtEk PHILIPPE "])
@pytest.mark.parametrize("sold_for", ["4500", "60000"])
def test_trades_of_another_brand_change_neither_worth_nor_limit(prices, trades, kind, brand, sold_for):
    trades()
    assert worth(prices, "3800", kind, brand) == Decimal("46750")
    assert buy_limit(prices, "3800", kind, brand) == Decimal("37000")

    trades(("Breguet", True, "1000", sold_for))

    assert worth(prices, "3800", kind, brand) == Decimal("46750")
    assert buy_limit(prices, "3800", kind, brand) == Decimal("37000")
    assert ours(prices, "3800", kind, brand=brand) == (2, Decimal("46750"))
    assert ours(prices, "3800", kind, sold=False, brand=brand) == (2, Decimal("37000"))


@pytest.mark.parametrize("brand", [None, "", " \t "])
def test_another_brand_still_counts_when_the_watchs_brand_is_unknown(prices, trades, brand):
    trades(("Breguet", True, "1000", "4500"))

    assert worth(prices, "3800", USED, brand) == Decimal("42000")
    assert buy_limit(prices, "3800", USED, brand) == most_to_pay(Decimal("42000"))
    assert ours(prices, "3800", USED, sold=False, brand=brand) == (3, Decimal("35000"))


@pytest.mark.parametrize("full_set", [True, False])
def test_the_agent_ignores_another_brand_including_when_choosing_full_sets(prices, trades, full_set):
    trades(("Breguet", True, "1000", "4500"), full_set=full_set)
    for kind in (USED, FULL_SET):
        searched(prices, 0, [], reference="3800", kind=kind)
    reading = Reading(is_watch_for_sale=True, brand="Patek Philippe", model="Nautilus", reference="3800",
                      year=None, condition="good", box=True, papers=True)

    verdict = decide(reading, Decimal("36000"), prices)

    assert (verdict.contact, verdict.worth, verdict.limit) == (True, Decimal("46750"), Decimal("37000"))


async def test_the_prices_page_ignores_another_brand_in_its_trades_worth_and_limits(prices, trades):
    prices.saw([WatchData(title="Nautilus", brand="Patek Philippe", reference="3800", price=Decimal("60000"),
                          url="https://shop.example/3800", site_name="Shop", site_key="shop", scraped_at=SEARCHED)])
    trades()
    app = web.Application()
    PricesPage(prices, "secret").add_to(app)
    async with TestClient(TestServer(app)) as client:
        before = await (await client.get(PATH, params={"key": key("secret")})).text()
        trades(("Breguet", True, "1000", "4500"))
        after = await (await client.get(PATH, params={"key": key("secret")})).text()

    row = before[before.index('id="3800"'):].split("</tr>")[0]
    assert "2 for 37.000 €</td><td class=n>2 for 46.750 €" in row
    assert row.count("46.750 €") == 3  # sales, used worth, full-set worth
    assert row.count("37.000 €") == 3  # purchases, used limit, full-set limit
    assert after[after.index('id="3800"'):].split("</tr>")[0] == row


@pytest.mark.parametrize("export_brand,watch_brand", [
    ("A Lange Sohne", "A. Lange & Söhne"),
    ("Bulgari", "Bvlgari"),
    ("Universal Geneve", "Universal Genève"),
    ("Glashuette", "Glashütte"),
])
@pytest.mark.parametrize("reverse", [False, True])
async def test_same_brand_spellings_count_while_another_brand_does_not(prices, trades, export_brand, watch_brand, reverse):
    if reverse:
        export_brand, watch_brand = watch_brand, export_brand
    trades((export_brand, True, "7000", "9000"))
    offers = chrono24_offers(*(["15000"] * 5), reference="3800")
    for offer in offers:
        offer.brand = watch_brand
    for kind in (USED, FULL_SET):
        searched(prices, 5, offers, reference="3800", kind=kind)
    reading = Reading(is_watch_for_sale=True, brand=watch_brand, model="Watch", reference="3800",
                      year=None, condition="good", box=False, papers=False)

    verdict = decide(reading, Decimal("9000"), prices)

    assert (verdict.worth, verdict.limit, verdict.contact) == (Decimal("9000"), Decimal("7000"), False)
    app = web.Application()
    PricesPage(prices, "secret").add_to(app)
    async with TestClient(TestServer(app)) as client:
        page = await (await client.get(PATH, params={"key": key("secret")})).text()

    row = page[page.index('id="3800"'):].split("</tr>")[0]
    assert "1 for 7.000 €</td><td class=n>1 for 9.000 €" in row
    assert row.count("9.000 €") == 3  # sales, used worth, full-set worth
    assert row.count("7.000 €") == 3  # purchases, used limit, full-set limit
