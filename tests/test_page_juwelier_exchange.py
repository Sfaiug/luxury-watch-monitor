"""Juwelier Exchange's scraper reads the first six cards of a saved copy of the shop's real watch page."""

from decimal import Decimal


def test_reduced_watches_have_the_price_to_pay(listed_watches):
    watches = listed_watches("juwelier_exchange")

    # Cards two to four are reduced: "55.500,00 € 57.500,00 € (3.48% gespart)"
    assert [w.price for w in watches] == [
        Decimal("15750"),
        Decimal("55500"),
        Decimal("15750"),
        Decimal("32750"),
        Decimal("12750"),
        Decimal("3450"),
    ]
    assert watches[1].price_display == "€55.500"
