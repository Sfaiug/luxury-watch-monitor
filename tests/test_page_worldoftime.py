"""World of Time's scraper reads a saved copy of the shop's real new-arrivals page."""

from decimal import Decimal


def test_every_priced_watch_has_its_price(listed_watches):
    watches = listed_watches("worldoftime")

    assert len(watches) == 16
    # The shop shows "Sold" in place of this one's price.
    assert [w.reference for w in watches if w.price is None] == ["5167A-001"]
    datejust = watches[0]
    assert (datejust.title, datejust.reference) == ("Rolex Datejust", "16014")
    assert datejust.price == Decimal("6250")
    assert datejust.price_display == "€6.250"
