"""What the business itself sold watches for, from the owner's controlling tool, in a watch's worth."""

import os
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import controlling
from chrono24 import FULL_SET, USED
from config import APP_CONFIG
from models import WatchData
from monitor import WatchMonitor
from prices import Prices
from prices_page import PATH, PricesPage, key
from worth import worth

# The export's own header (11 Oct 2026); the rows are made up, the seller column as full as in the real one
HEADER = (
    "Artikelnummer,Marke,Modell,Referenznummer,Seriennummer,Box,Papiere,Verkäufer,Ankaufdatum,Verkaufsdatum,Month,Jahr,"
    "Ankaufdatum Monat.Jahr,Verkaufsdatum Monat.Jahr,EK,Kosten,VK geplant,VK realisiert,Realisierter Ertrag vor Steuern,"
    "Realisierter Ertrag vor Steuern nach Kosten,Umschlagzeit,Differenzbesteuerungsbetrag,Noch im Bestand?,Bestands-EK,"
    "Bestands-VK geplant,Hilfspalte Warenbestand,Rechnung vorhanden,RG-Nummer,Weitere Kostenpunkte,"
    "Hilfspalte Ankauf Monat,Hilfspalte Ankauf Jahr"
)


def day(days_ago):
    return (date.today() - timedelta(days=days_ago)).strftime("%d.%m.%Y")


def row(reference, box, papers, bought, paid, sold="", sold_for=""):
    return (f'1,Rolex,Submariner,{reference},X123,{box},{papers},A Seller,{bought},{sold},1,2026,,,"{paid}",,,'
            f'"{sold_for}",,,,,{"" if sold else "1"},,,0,,,,1,2026')


@pytest.fixture
def export(tmp_path):
    path = tmp_path / "controlling.csv"
    path.write_text("\n".join([
        HEADER,
        row("116610LN", "x", "x", day(60), "€8.100,000", day(40), "9.900,00 €"),
        row("116610 LN", "-", "x (Extract)", day(50), "€7.200,00", day(30), "8.800,00 €"),
        row("116610LN", "X", "X", day(500), "€6.000,00", day(400), "7.000,00 €"),  # more than a year ago
        row("116610LN", "x", "x", day(5), "€8.500,00"),  # still in stock
        row("", "x", "x", day(5), "€100,00"),
    ]), encoding="utf-8-sig")
    return path


def test_an_export_reads_as_the_trades_with_nothing_of_the_seller(export):
    trades = controlling.read(export)

    assert [(t.reference, t.full_set, t.paid, t.sold_for) for t in trades] == [
        ("116610LN", True, Decimal("8100.000"), Decimal("9900.00")),
        ("116610LN", False, Decimal("7200.00"), Decimal("8800.00")),  # an extract is not the papers
        ("116610LN", True, Decimal("6000.00"), Decimal("7000.00")),
        ("116610LN", True, Decimal("8500.00"), None),
    ]
    assert trades[0].sold == date.today() - timedelta(days=40)
    assert set(vars(trades[0])) == {"reference", "full_set", "bought", "paid", "sold", "sold_for"}


def chrono24(prices, kind, *asked):
    prices.searched("116610LN", kind, len(asked), [
        WatchData(title="Submariner", url=f"https://www.chrono24.de/{kind}-{n}", site_name="Chrono24",
                  site_key="chrono24", reference="116610LN", price=Decimal(price), scraped_at=datetime.now())
        for n, price in enumerate(asked)
    ], datetime.now())


def test_a_watch_is_worth_the_lower_of_the_market_and_the_middle_of_our_sales_within_a_year(tmp_path, export):
    prices = Prices(tmp_path / "prices.sqlite3")
    prices.traded(controlling.read(export))

    # Too few offers: our sales alone, the year's two used ones, and the one full set for a full set
    assert worth(prices, "116610LN", USED) == Decimal("9350")
    assert worth(prices, "116610LN", FULL_SET) == Decimal("9900")

    chrono24(prices, USED, "9000", "9100", "9200", "9300", "9400")
    chrono24(prices, FULL_SET, "10500", "10600", "10700", "10800", "10900")
    assert worth(prices, "116610LN", USED) == Decimal("9100")  # the market's lower
    assert worth(prices, "116610LN", FULL_SET) == Decimal("9900")  # ours lower


def test_a_newer_export_takes_the_place_of_the_last_one(tmp_path, export, monkeypatch):
    monkeypatch.setattr(APP_CONFIG, "controlling_file", str(export))
    monitor = WatchMonitor(log_level="ERROR")
    monitor.prices = Prices(tmp_path / "prices.sqlite3")

    monitor._read_trades()
    assert len(monitor.prices.sales("116610LN", False, date.today() - timedelta(days=365))) == 2

    export.write_text("\n".join([HEADER, row("126610LN", "x", "x", day(9), "€9.000,00", day(3), "11.000,00 €")]),
                      encoding="utf-8-sig")
    os.utime(export, (export.stat().st_atime, export.stat().st_mtime + 60))
    monitor._read_trades()

    assert monitor.prices.sales("116610LN", False, date(2000, 1, 1)) == []
    assert monitor.prices.sales("126610LN", True, date(2000, 1, 1)) == [11000.0]


async def test_the_owner_sees_what_we_sold_a_watch_for_within_a_year(tmp_path, export):
    prices = Prices(tmp_path / "prices.sqlite3")
    prices.saw([WatchData(title="Submariner", url="https://shop.example/1", site_name="Shop", site_key="worldoftime",
                          brand="Rolex", reference="116610LN", price=Decimal("9500"), scraped_at=datetime.now())])
    prices.traded(controlling.read(export))
    app = web.Application()
    PricesPage(prices, "secret").add_to(app)

    async with TestClient(TestServer(app)) as client:
        page = await (await client.get(PATH, params={"key": key("secret")})).text()

    rolex = page[page.index('id="116610LN"'):].split("</tr>")[0]
    assert "2 for 9.350 €" in rolex
