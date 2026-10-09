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


def test_a_watch_has_its_name_and_brand_from_its_card(listed_watches):
    watch = listed_watches("juwelier_exchange")[3]

    # This watch's own page answers 404 at the shop: its name has a "/"
    assert watch.title.startswith("Herrenuhr Rolex 'Day-Date' Ø 40 mm Ref. 228239")
    assert "750 Weißgold / 211,8 g" in watch.title
    assert watch.brand == "Rolex"
