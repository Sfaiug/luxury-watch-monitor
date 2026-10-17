"""What the business itself sold watches for, from the owner's controlling tool, in a watch's worth."""

import os
import sqlite3
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
from worth import RECENT, buy_limit, most_to_pay, worth

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
        row("116610LN", "X", "X", day(150), "€6.000,00", day(120), "7.000,00 €"),  # too long ago to count
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
    assert trades[0].brand == "Rolex"
    assert set(vars(trades[0])) == {"reference", "brand", "full_set", "bought", "paid", "sold", "sold_for"}


def chrono24(prices, kind, *asked):
    prices.searched("116610LN", kind, len(asked), [
        WatchData(title="Submariner", url=f"https://www.chrono24.de/{kind}-{n}", site_name="Chrono24",
                  site_key="chrono24", reference="116610LN", price=Decimal(price), scraped_at=datetime.now())
        for n, price in enumerate(asked)
    ], datetime.now())


def test_a_watch_is_worth_the_lower_of_the_market_and_the_middle_of_our_recent_sales(tmp_path, export):
    prices = Prices(tmp_path / "prices.sqlite3")
    prices.traded(controlling.read(export))

    # Too few offers: our sales alone, the two recent used ones, and the one full set for a full set
    assert worth(prices, "116610LN", USED) == Decimal("9350")
    assert worth(prices, "116610LN", FULL_SET) == Decimal("9900")

    chrono24(prices, USED, "9000", "9100", "9200", "9300", "9400")
    chrono24(prices, FULL_SET, "10500", "10600", "10700", "10800", "10900")
    assert worth(prices, "116610LN", USED) == Decimal("9100")  # the market's lower
    assert worth(prices, "116610LN", FULL_SET) == Decimal("9900")  # ours lower


def test_the_most_to_pay_is_no_more_than_the_middle_of_what_we_paid_lately(tmp_path, export):
    prices = Prices(tmp_path / "prices.sqlite3")
    prices.traded(controlling.read(export))
    # Paid 7.200, 8.100 and 8.500 lately: more than selling at 9.350 leaves room for
    assert buy_limit(prices, "116610LN", USED) == most_to_pay(Decimal("9350"))

    export.write_text("\n".join([
        HEADER,
        row("126610LN", "x", "x", day(90), "€6.000,00", day(60), "11.000,00 €"),
        row("126610LN", "x", "x", day(20), "€6.400,00"),
        row("126610LN", "-", "-", day(10), "€5.000,00"),
    ]), encoding="utf-8-sig")
    prices.traded(controlling.read(export))
    assert most_to_pay(Decimal("11000")) > Decimal("6400")
    assert buy_limit(prices, "126610LN", USED) == Decimal("6000")  # the middle of all three
    assert buy_limit(prices, "126610LN", FULL_SET) == Decimal("6200")  # of the two full sets


async def test_a_newer_export_takes_the_place_of_the_last_one(tmp_path, export, monkeypatch):
    monkeypatch.setattr(APP_CONFIG, "controlling_file", str(export))
    monitor = WatchMonitor(log_level="ERROR")
    monitor.prices = Prices(tmp_path / "prices.sqlite3")

    await monitor._read_trades()
    assert len(monitor.prices.traded_for("116610LN", False, date.today() - RECENT, True)) == 2

    export.write_text("\n".join([
        HEADER,
        row("126610LN", "x", "x", day(9), "€9.000,00", day(3), "11.000,00 €"),
        row("126610LN", "x", "x", day(50), "€8.000,00", day(30), "10.000,00 €"),
        row("126610LN", "x", "x", day(500), "€7.000,00", day(400), "9.000,00 €"),
        row("126610LN", "x", "x", day(5), "€9.500,00"),
    ]), encoding="utf-8-sig")
    os.utime(export, (export.stat().st_atime, export.stat().st_mtime + 60))
    await monitor._read_trades()

    assert monitor.prices.traded_for("116610LN", False, date(2000, 1, 1), True) == []
    assert monitor.prices.traded_for("126610LN", True, date(2000, 1, 1), True) == [9000, 10000, 11000]


@pytest.mark.parametrize("field,value", [
    ("bought", "2026-10-14"), ("bought", "14.10.26"),
    ("sold", "2026-10-14"), ("sold", "14.10.26"),
    ("paid", "1.000,-"), ("paid", "30,000.00"),
    ("sold_for", "1.000,-"), ("sold_for", "30,000.00"),
])
def test_unreadable_export_does_not_pass_when_days_or_amounts_stop_reading(export, field, value):
    values = dict(bought=day(9), paid="€8.000,00", sold=day(3), sold_for="10.000,00 €")
    values[field] = value
    export.write_text("\n".join([HEADER, *[row("116610LN", "x", "x", **values) for _ in range(4)]]),
                      encoding="utf-8-sig")

    with pytest.raises(ValueError, match="Readable purchases.*readable sales.*DD.MM.YYYY"):
        controlling.read(export, (4, 3))


@pytest.mark.parametrize("problem,reason", [
    ("renamed", "Missing CSV columns:.*EK"),
    ("semicolon", "comma-separated"),
    ("encoding", "UTF-8"),
    ("short_row", "wrong number of columns"),
    ("extra_column", "wrong number of columns"),
    ("quote", "invalid quoting"),
    ("empty", "Missing CSV columns"),
    ("header_only", "Readable purchases: 0"),
])
def test_unreadable_export_explains_the_format_without_seller_details(export, problem, reason):
    content = export.read_text(encoding="utf-8-sig")
    if problem == "renamed":
        content = content.replace(",EK,", ",Einkauf,")
    elif problem == "semicolon":
        content = content.replace(",", ";")
    elif problem == "encoding":
        export.write_bytes(content.encode("cp1252"))
    elif problem == "short_row":
        content += "\n1,Rolex"
    elif problem == "extra_column":
        content += "\n" + row("116610LN", "x", "x", day(9), "8000") + ",extra"
    elif problem == "quote":
        content += '\n"unfinished'
    elif problem == "empty":
        content = ""
    elif problem == "header_only":
        content = HEADER
    if problem != "encoding":
        export.write_text(content, encoding="utf-8-sig")

    with pytest.raises(ValueError, match=reason) as error:
        controlling.read(export, (4, 3))
    assert "A Seller" not in str(error.value)


@pytest.mark.parametrize("unreadable,accepted", [(1, True), (2, False)])
def test_unreadable_export_allows_only_a_small_drop_in_readable_rows(export, unreadable, accepted):
    export.write_text("\n".join([
        HEADER,
        *[row("116610LN", "x", "x", "unknown" if i < unreadable else day(9), "8.000,00",
              day(3), "10.000,00") for i in range(10)],
    ]), encoding="utf-8-sig")

    if accepted:
        assert len(controlling.read(export, (10, 10))) == 10
    else:
        with pytest.raises(ValueError, match="Readable purchases: 8"):
            controlling.read(export, (10, 10))


def test_unreadable_export_with_no_readable_trades_is_rejected_without_a_baseline(export):
    export.write_text("\n".join([
        HEADER, row("116610LN", "x", "x", "2026-10-14", "8.000,00", "14.10.26", "10.000,00"),
    ]), encoding="utf-8-sig")

    with pytest.raises(ValueError, match="Readable purchases: 0.*readable sales: 0"):
        controlling.read(export)


def test_existing_trades_gain_their_brand_when_the_export_is_read_again(tmp_path, export):
    path = tmp_path / "prices.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE trades (reference TEXT, full_set INTEGER, bought TEXT, paid REAL, sold TEXT, sold_for REAL)")
        db.execute("INSERT INTO trades VALUES ('116610LN', 1, NULL, NULL, ?, 9500)", (date.today().isoformat(),))
    db.close()

    prices = Prices(path)
    assert prices.traded_for("116610LN", False, date(2000, 1, 1), True) == [9500]
    assert prices.traded_for("116610LN", False, date(2000, 1, 1), True, "Rolex") == []
    prices.traded(controlling.read(export))
    prices.close()

    prices = Prices(path)
    assert prices.traded_for("116610LN", False, date.today() - RECENT, True, "Rolex") == [8800, 9900]
    assert prices.traded_for("116610LN", False, date(2000, 1, 1), True, "Omega") == []
    prices.close()


async def test_the_owner_sees_what_we_bought_and_sold_a_watch_for_lately(tmp_path, export):
    prices = Prices(tmp_path / "prices.sqlite3")
    prices.saw([WatchData(title="Submariner", url="https://shop.example/1", site_name="Shop", site_key="worldoftime",
                          brand="Rolex", reference="116610LN", price=Decimal("9500"), scraped_at=datetime.now())])
    prices.traded(controlling.read(export))
    app = web.Application()
    PricesPage(prices, "secret").add_to(app)

    async with TestClient(TestServer(app)) as client:
        page = await (await client.get(PATH, params={"key": key("secret")})).text()

    rolex = page[page.index('id="116610LN"'):].split("</tr>")[0]
    assert "3 for 8.100 €</td><td class=n>2 for 9.350 €" in rolex
