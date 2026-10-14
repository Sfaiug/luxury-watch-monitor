"""The owner's page of watch prices: what each watch is worth, the most to pay, and the owner's own buy price."""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from bs4 import BeautifulSoup

import chrono24
from chrono24 import FULL_SET, USED
from config import APP_CONFIG
from controlling import Trade
from models import WatchData
from prices import Prices
from prices_page import PATH, PricesPage, key
from worth import buy_limit, calculated_limit

SECRET = "the-owner-s-secret"
SEARCHED = datetime(2026, 10, 10, 11, 0)
PAGE = (Path(__file__).parent / "pages" / "chrono24.html").read_text(encoding="utf-8")


@pytest.fixture
def prices(tmp_path):
    kept = Prices(tmp_path / "prices.sqlite3")
    found, offers = chrono24.read(PAGE, "Rolex", "116610LN", SEARCHED)
    kept.searched("116610LN", USED, found, offers, SEARCHED)
    kept.searched("116610LN", FULL_SET, 0, [], SEARCHED)
    kept.saw([
        WatchData(
            title="Patek Philippe Nautilus",
            url="https://shop.example/5711",
            site_name="World of Time",
            site_key="worldoftime",
            brand="Patek Philippe",
            model="Nautilus",
            reference="5711/1A-010",
            price=Decimal("120000"),
            scraped_at=SEARCHED,
        )
    ])
    return kept


@pytest.fixture
async def client(prices):
    app = web.Application()
    PricesPage(prices, SECRET).add_to(app)
    async with TestClient(TestServer(app)) as client:
        yield client


async def test_the_page_opens_only_from_its_link(client):
    assert (await client.get(PATH)).status == 403
    assert (await client.get(PATH, params={"key": "guessed"})).status == 403
    assert (await client.post(PATH, params={"key": "guessed"}, data={"reference": "116610LN", "price": "1"})).status == 403


async def test_each_watch_shows_its_market_worth_and_most_to_pay(client):
    page = await (await client.get(PATH, params={"key": key(SECRET)})).text()

    rolex = page[page.index('id="116610LN"'):].split("</tr>")[0]
    assert "192 used, 0 of them full sets, <time>2026-10-10</time>" in rolex  # a date kept whole on its line
    bought, sold, used, full_set = rolex.split("<td class=n>")[1:5]
    assert bought.startswith("–") and sold.startswith("–")  # bought and sold by us within the year: none
    assert "10.800 €" in used and "8.608 €" in used  # worth, the 48th cheapest of 192, and most to pay
    assert full_set.count("–") == 2  # no full set offered: no worth, no most to pay

    patek = page[page.index('id="57111A010"'):].split("</tr>")[0]
    assert "Patek Philippe" in patek
    assert "not searched yet" in patek


async def test_the_owner_s_price_is_the_limit_in_place_of_the_worked_out_one(client, prices):
    answer = await client.post(
        PATH, params={"key": key(SECRET)}, data={"reference": "116610LN", "price": "8.200"}, allow_redirects=False
    )
    assert answer.status == 303
    assert answer.headers["Location"] == f"{PATH}?key={key(SECRET)}#116610LN"
    assert prices.buy_price("116610LN") == 8200
    assert buy_limit(prices, "116610LN", USED) == buy_limit(prices, "116610LN", FULL_SET) == Decimal("8200")

    page = await (await client.get(PATH, params={"key": key(SECRET)})).text()
    rolex = page[page.index('id="116610LN"'):].split("</tr>")[0]
    assert 'class="own"' in rolex
    assert 'value="8200"' in rolex
    assert "8.608 €" in rolex  # the worked-out limit stays visible beside the owner's price

    await client.post(PATH, params={"key": key(SECRET)}, data={"reference": "116610LN", "price": ""})
    assert prices.buy_price("116610LN") is None
    assert buy_limit(prices, "116610LN", USED) == Decimal("8608")


@pytest.mark.parametrize("given", ["cheap", "-500", "0", "nan", "snan", "1e400", "1e-400"])
async def test_a_buy_price_is_a_number_of_euros_above_nothing(client, prices, given):
    answer = await client.post(PATH, params={"key": key(SECRET)}, data={"reference": "116610LN", "price": given})

    assert answer.status == 400
    assert prices.buy_price("116610LN") is None


def test_a_watch_without_enough_offers_has_no_limit_until_the_owner_sets_one(prices):
    assert buy_limit(prices, "5711/1A-010", USED) is None

    prices.set_buy_price("5711/1A-010", 95000, SEARCHED)
    assert buy_limit(prices, "57111A010", USED) == Decimal("95000")


@pytest.mark.parametrize("given,amount", [("400000", 400000), ("4000", 4000), ("40.00", 40)])
@pytest.mark.parametrize("previous", [None, 8200, 400000])
async def test_a_price_far_from_the_limit_counts_only_after_confirmation(client, prices, given, amount, previous):
    prices.set_buy_price("116610LN", previous, SEARCHED)
    answer = await client.post(
        PATH, params={"key": key(SECRET)}, data={"reference": "116610LN", "price": given}, allow_redirects=False
    )

    assert answer.status == 200
    assert prices.buy_price("116610LN") == previous
    assert buy_limit(prices, "116610LN", USED) == Decimal(str(previous if previous is not None else 8608))
    warning = BeautifulSoup(await answer.text(), "html.parser")
    assert "Worked-out limit: used: 8.608 €, full set: –" in warning.get_text()
    assert "It has not been saved" in warning.get_text()
    form = warning.find("form")
    data = {field["name"]: field["value"] for field in form.select("input, button")}

    confirmed = await client.post(form["action"], data=data, allow_redirects=False)
    assert confirmed.status == 303
    assert prices.buy_price("116610LN") == amount
    assert buy_limit(prices, "116610LN", USED) == buy_limit(prices, "116610LN", FULL_SET) == Decimal(amount)
    assert calculated_limit(prices, "116610LN", USED) == Decimal("8608")
    page = await (await client.get(confirmed.headers["Location"])).text()
    row = page[page.index('id="116610LN"'):].split("</tr>")[0]
    assert "8.608 €" in row and f'value="{amount}"' in row

    await client.post(PATH, params={"key": key(SECRET)}, data={"reference": "116610LN", "price": ""})
    assert prices.buy_price("116610LN") is None
    assert buy_limit(prices, "116610LN", USED) == Decimal("8608")


@pytest.mark.parametrize("given,far", [("4303.99", True), ("4304", False), ("12912", False), ("12912.01", True)])
async def test_a_price_far_from_the_limit_is_strictly_outside_half_to_one_and_a_half(client, prices, given, far):
    answer = await client.post(
        PATH, params={"key": key(SECRET)}, data={"reference": "116610LN", "price": given}, allow_redirects=False
    )
    assert answer.status == (200 if far else 303)
    assert prices.buy_price("116610LN") == (None if far else float(given))


async def test_confirmation_of_a_price_far_from_the_limit_does_not_confirm_another_price(client, prices):
    answer = await client.post(PATH, params={"key": key(SECRET)}, data={"reference": "116610LN", "price": "4000"})
    form = BeautifulSoup(await answer.text(), "html.parser").find("form")
    data = {field["name"]: field["value"] for field in form.select("input, button")}
    data["price"] = "400000"

    answer = await client.post(form["action"], data=data, allow_redirects=False)
    assert answer.status == 200
    assert prices.buy_price("116610LN") is None

    # Cancel returns to the prices page without changing the limit.
    cancel = BeautifulSoup(await answer.text(), "html.parser").find("a")
    assert (await client.get(cancel["href"])).status == 200
    assert buy_limit(prices, "116610LN", USED) == Decimal("8608")


@pytest.mark.parametrize("found", [0, 4])
@pytest.mark.parametrize("given,amount", [("400000", 400000), ("40.00", 40)])
async def test_a_price_far_from_the_limit_needs_no_confirmation_without_a_worked_out_limit(client, prices, found, given, amount):
    _, offers = chrono24.read(PAGE, "Rolex", "116610LN", SEARCHED)
    prices.searched("116610LN", USED, found, offers[:found], SEARCHED)
    prices.set_buy_price("116610LN", 8200, SEARCHED)

    answer = await client.post(
        PATH, params={"key": key(SECRET)}, data={"reference": "116610LN", "price": given}, allow_redirects=False
    )
    assert answer.status == 303
    assert prices.buy_price("116610LN") == amount


async def test_a_price_far_from_the_limit_is_checked_when_only_full_sets_have_a_limit(client, prices):
    found, offers = chrono24.read(PAGE, "Rolex", "116610LN", SEARCHED)
    prices.searched("116610LN", FULL_SET, found, offers, SEARCHED)
    prices.searched("116610LN", USED, 0, [], SEARCHED)

    answer = await client.post(PATH, params={"key": key(SECRET)}, data={"reference": "116610LN", "price": "400000"})
    assert answer.status == 200
    assert "used: –, full set: 8.608 €" in await answer.text()
    assert prices.buy_price("116610LN") is None


@pytest.mark.parametrize("given,far", [("4000", False), ("8000", True)])
async def test_a_price_far_from_the_limit_uses_past_purchases_of_the_watchs_brand(client, prices, given, far):
    prices.traded([
        Trade("116610LN", True, date.today(), Decimal("5000"), None, None, "Rolex"),
        Trade("116610LN", True, date.today(), Decimal("1"), None, None, "Breguet"),
    ])

    answer = await client.post(
        PATH, params={"key": key(SECRET)}, data={"reference": "116610 ln", "price": given}, allow_redirects=False
    )
    assert answer.status == (200 if far else 303)
    assert prices.buy_price("116610LN") == (None if far else float(given))
    if far:
        assert "used: 5.000 €" in await answer.text()


async def test_a_positive_price_far_from_the_limit_needs_confirmation_when_the_limit_is_zero(client, prices, monkeypatch):
    monkeypatch.setattr(APP_CONFIG, "least_profit_eur", 15000)
    answer = await client.post(PATH, params={"key": key(SECRET)}, data={"reference": "116610LN", "price": "8200"})

    assert answer.status == 200
    assert "used: 0 €" in await answer.text()
    assert prices.buy_price("116610LN") is None
