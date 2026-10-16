"""What a watch is worth, and the most to pay for it, from its Chrono24 offers inside the EU."""

import csv
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from bs4 import BeautifulSoup

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


@pytest.mark.parametrize("kind", [USED, FULL_SET])
@pytest.mark.parametrize("on_request,asked,expected", [
    (5, (58000,), None),
    (1, (48000, 50000, 52000, 54000), None),
    (4, (48000, 50000, 52000, 54000, 56000), Decimal("50000")),
    (2, (450, 850, 48000, 50000, 52000, 54000), None),
    (4, (450, 850, 48000, 50000, 52000, 54000, 56000), Decimal("50000")),
])
def test_only_priced_offers_count_toward_the_minimum_and_quarter(prices, kind, on_request, asked, expected):
    # Live, 16 Oct 2026: six EU offers, five on request, left one price of 58,000 euros.
    soup = BeautifulSoup(PAGE, "lxml")
    found = len(asked) + on_request
    soup.find("strong").string = f"{found} Inserate"
    for n, card in enumerate(soup.select(".js-listing-item-container")):
        if n >= found:
            card.decompose()
        else:
            card.select_one(".wt-listing-item-price").string = (
                f"{asked[n]} €" if n < len(asked) else "Preis auf Anfrage"
            )
    count, offers = chrono24.read(str(soup), "Rolex", "116610LN", SEARCHED)
    searched(prices, count, offers, kind=kind)

    assert worth(prices, "116610LN", kind) == expected
    assert buy_limit(prices, "116610LN", kind) == (most_to_pay(expected) if expected is not None else None)


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


@pytest.mark.parametrize("kind", [USED, FULL_SET])
@pytest.mark.parametrize("found,asked,expected", [
    (9, (450, 850, 47000, 47500, 48000, 49000, 50000, 51000, 52000), Decimal("47500")),
    (6, (450, 850, 47500, 50000, 55000, 60000), None),
    (7, (450, 850, 47500, 50000, 55000, 60000, 65000), Decimal("50000")),
    # The quarter still uses all offers found, including those beyond the cards read.
    (25, (450, 47000, 47500, 48000, 49000, 50000, 51000, 52000, 53000), Decimal("51000")),
    # Exactly half the median counts; only the price below it is junk.
    (7, (9999, 10000, 10000, 20000, 21000, 22000, 23000), Decimal("10000")),
])
def test_junk_counts_neither_toward_the_quarter_nor_the_five_offers_needed(prices, kind, found, asked, expected):
    searched(prices, found, chrono24_offers(*asked), kind=kind)

    assert worth(prices, "116610LN", kind) == expected


@pytest.mark.parametrize("asked,expected", [
    ((450, 850, 50000, 52000, 55000, 60000), None),
    ((450, 850, 42000, 45000, 48000, 50000, 52000), Decimal("47500")),
    ((42000, 45000, 48000, 50000, 52000), Decimal("47500")),
    ((450, 850, 52000, 55000, 58000, 60000, 62000), Decimal("55000")),
])
def test_a_full_set_with_junk_never_falls_below_used_worth_or_starts_at_an_accessory_price(prices, asked, expected):
    searched(prices, 5, chrono24_offers(45000, 47500, 49000, 50000, 52000, reference="3800"), reference="3800")
    full_sets = chrono24_offers(*asked, reference="3800")
    for offer in full_sets:
        offer.url = offer.url.replace("--id", "-full-set--id")
    searched(prices, len(full_sets), full_sets, reference="3800", kind=FULL_SET)
    reading = Reading(is_watch_for_sale=True, brand="Patek Philippe", model="Nautilus", reference="3800",
                      year=None, condition="good", box=True, papers=True)

    verdict = decide(reading, Decimal("42000"), prices)

    assert worth(prices, "3800", USED) == Decimal("47500")
    assert worth(prices, "3800", FULL_SET) == expected
    value = expected if expected is not None else Decimal("47500")
    assert (verdict.contact, verdict.worth, verdict.limit) == (True, value, most_to_pay(value))
    assert verdict.opening > Decimal("30000")


def test_junk_filtering_leaves_the_business_s_own_lower_sales_in_place(prices, trades):
    trades()
    for kind in (USED, FULL_SET):
        searched(prices, 7, chrono24_offers(450, 850, 52000, 55000, 58000, 60000, 62000, reference="3800"),
                 reference="3800", kind=kind)

    assert worth(prices, "3800", USED, "Patek Philippe") == Decimal("46750")
    assert worth(prices, "3800", FULL_SET, "Patek Philippe") == Decimal("46750")
    assert buy_limit(prices, "3800", FULL_SET, "Patek Philippe") == Decimal("37000")


@pytest.mark.parametrize("junk", [(), (450, 850)])
def test_a_full_sets_lower_own_sales_cap_survives_the_junk_floor(prices, junk):
    asked = (48000, 50000, 53000, 55000, 58000, 60000, 62000)
    for kind, amounts in ((USED, asked), (FULL_SET, asked[2:])):
        offers = chrono24_offers(*junk, *amounts, reference="3800")
        for offer in offers:
            offer.url = offer.url.replace("--id", f"-{kind}--id")
        searched(prices, len(offers), offers, reference="3800", kind=kind)
    prices.traded([
        controlling.Trade("3800", full_set, None, None, date.today(), Decimal(amount), "Patek Philippe")
        for full_set, amount in ((True, 40000), (False, 60000), (False, 62000))
    ])
    reading = Reading(is_watch_for_sale=True, brand="Patek Philippe", model="Nautilus", reference="3800",
                      year=None, condition="good", box=True, papers=True)

    verdict = decide(reading, Decimal("42000"), prices)

    assert worth(prices, "3800", USED, "Patek Philippe") == Decimal("50000")
    assert worth(prices, "3800", FULL_SET, "Patek Philippe") == Decimal("40000")
    assert buy_limit(prices, "3800", FULL_SET, "Patek Philippe") == Decimal("32074")
    assert (verdict.contact, verdict.worth, verdict.limit) == (False, Decimal("40000"), Decimal("32074"))


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
