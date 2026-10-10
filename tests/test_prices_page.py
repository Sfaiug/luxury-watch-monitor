"""The owner's page of watch prices: what each watch is worth, the most to pay, and the owner's own buy price."""

from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import chrono24
from models import WatchData
from prices import Prices
from prices_page import PATH, PricesPage, key
from worth import buy_limit

SECRET = "the-owner-s-secret"
SEARCHED = datetime(2026, 10, 10, 11, 0)
PAGE = (Path(__file__).parent / "pages" / "chrono24.html").read_text(encoding="utf-8")


@pytest.fixture
def prices(tmp_path):
    kept = Prices(tmp_path / "prices.sqlite3")
    found, offers = chrono24.read(PAGE, "Rolex", "116610LN", SEARCHED)
    kept.searched("116610LN", found, offers, SEARCHED)
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
    assert "192 offers, <time>2026-10-10</time>" in rolex  # a date kept whole on its line
    assert "10.800 €" in rolex  # worth: the 48th cheapest of 192
    assert "8.608 €" in rolex  # most to pay, and the limit while the owner sets none

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
    assert buy_limit(prices, "116610LN") == Decimal("8200")

    page = await (await client.get(PATH, params={"key": key(SECRET)})).text()
    rolex = page[page.index('id="116610LN"'):].split("</tr>")[0]
    assert 'class="own"' in rolex
    assert 'value="8200"' in rolex

    await client.post(PATH, params={"key": key(SECRET)}, data={"reference": "116610LN", "price": ""})
    assert prices.buy_price("116610LN") is None
    assert buy_limit(prices, "116610LN") == Decimal("8608")


@pytest.mark.parametrize("given", ["cheap", "-500", "0", "nan", "1e400", "1e-400"])
async def test_a_buy_price_is_a_number_of_euros_above_nothing(client, prices, given):
    answer = await client.post(PATH, params={"key": key(SECRET)}, data={"reference": "116610LN", "price": given})

    assert answer.status == 400
    assert prices.buy_price("116610LN") is None


def test_a_watch_without_enough_offers_has_no_limit_until_the_owner_sets_one(prices):
    assert buy_limit(prices, "5711/1A-010") is None

    prices.set_buy_price("5711/1A-010", 95000, SEARCHED)
    assert buy_limit(prices, "57111A010") == Decimal("95000")
