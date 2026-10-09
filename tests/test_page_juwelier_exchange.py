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


def test_a_watch_is_named_by_its_card(listed_watches):
    watch = listed_watches("juwelier_exchange")[3]

    # This watch's own page answers 404 at the shop: its name has a "/"
    assert watch.title.startswith("Herrenuhr Rolex 'Day-Date' Ø 40 mm Ref. 228239")
    assert "750 Weißgold / 211,8 g" in watch.title
    assert (watch.brand, watch.model) == ("Rolex", "Day-Date")
    assert watch.to_discord_embed(0)["title"] == "Rolex Day-Date"


def test_a_watch_keeps_the_former_id_the_server_remembers(listed_watches):
    """As tests/test_announce_once.py pins it for this watch."""
    watch = listed_watches("juwelier_exchange")[0]

    assert watch.url.endswith("/978973/herrenuhr-rolex-gmt-master-ii-automatik")
    assert watch.former_id == "1cface00f8114163f5a3ba58f3b852ee"
