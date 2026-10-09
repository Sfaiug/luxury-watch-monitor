"""Rüschenbeck's scraper reads the first eight cards of a saved copy of the shop's real pre-owned page."""

from decimal import Decimal


def test_a_card_gives_what_the_alert_shows(listed_watches):
    watches = listed_watches("rueschenbeck")

    assert len(watches) == 8
    tank = watches[1]
    assert (tank.brand, tank.model, tank.reference) == ("Cartier", "Tank Louis", "2441")
    assert tank.price == Decimal("9290")
    assert tank.condition == "★★★★☆"  # certified pre-owned
    assert tank.url == (
        "https://www.rueschenbeck.de/cartier-tank-louis-2441-494688-certified-pre-owned"
    )
    assert tank.image_url.startswith("https://")
    # Two Lady-Datejust 179313 are two listings
    assert len({watch.url for watch in watches}) == 8


def test_a_reduced_watch_has_the_price_to_pay(listed_watches):
    datejust = listed_watches("rueschenbeck")[0]

    # Its price block reads "9.950,00 € 10.490,00 €": the price, then the old one
    assert datejust.reference == "116234"
    assert datejust.price == Decimal("9950")
    assert datejust.price_display == "€9.950"
