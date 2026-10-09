"""World of Time's scraper reads a saved copy of the shop's real new-arrivals page."""

from decimal import Decimal


def test_every_priced_watch_has_its_price(listed_watches):
    watches = listed_watches("worldoftime")

    # The eight newest in the section on top, sixteen in the list below it
    assert len(watches) == 24
    # The shop shows "Sold" in place of this one's price.
    assert [w.reference for w in watches if w.price is None] == ["5167A-001"]
    datejust = watches[8]
    assert (datejust.title, datejust.reference) == ("Rolex Datejust", "16014")
    assert datejust.price == Decimal("6250")
    assert datejust.price_display == "€6.250"


def test_the_newest_watches_are_read(listed_watches):
    newest = listed_watches("worldoftime")[0]

    assert newest.title == "Audemars Piguet Royal Oak"
    assert newest.reference == "25860ST.O.1110ST.03"
    assert newest.price == Decimal("31500")  # "€ 31,500,-"
    assert newest.year == "2000"
    assert newest.url.endswith("/Watches/audemars-piguet/royal-oak-D1B2B40")
