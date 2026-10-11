"""What the buying agent answers a seller, by the owner's terms."""

import pytest

from negotiation import Move, SellerSays, Terms, move

LIMIT, OPENING = 8600, 7550


def says(**said):
    stated = dict(price=None, accepts_offer=False, bank_transfer=None, delivery=None, contract=None, id_card=None,
                  ended=False, red_flags=[], question=None)
    stated.update(said)
    return SellerSays(**stated)


def test_an_offer_the_seller_accepts_is_the_price_and_the_rest_is_settled_next():
    terms = Terms()

    answer = move(LIMIT, OPENING, terms, says(accepts_offer=True), pictures=False)

    assert (answer.kind, answer.price, terms.price) == ("settle", 7550, 7550)
    assert terms.open() == ["payment by bank transfer", "insured shipping, or else pickup", "the purchase contract",
                            "a picture of the seller's ID card"]


def test_a_seller_asking_a_little_more_is_met_at_their_price():
    answer = move(LIMIT, OPENING, Terms(), says(price=7700), False)
    assert (answer.kind, answer.price) == ("settle", 7700)
    assert move(LIMIT, OPENING, Terms(), says(price=7000), False).price == 7000  # below the offer: theirs


def test_the_agent_gives_half_the_room_to_its_limit_and_no_more_than_halfway_to_the_seller():
    assert move(LIMIT, OPENING, Terms(), says(price=8500), False) == Move("offer", 8000, "the seller asks 8.500 €")

    # A seller who holds out far above the limit: 8.000, 8.300, 8.450, 8.500, then the limit as the last offer
    offers, offered = [], 8000
    while offered < LIMIT:
        answer = move(LIMIT, offered, Terms(), says(price=11000), False)
        offers.append((answer.kind, answer.price))
        offered = answer.price
    assert offers == [("offer", 8300), ("offer", 8450), ("offer", 8500), ("final", LIMIT)]

    assert move(LIMIT, LIMIT, Terms(), says(price=9500), False).kind == "farewell"


@pytest.mark.parametrize("refusing", [dict(bank_transfer=False), dict(contract=False), dict(id_card=False)])
def test_a_seller_refusing_one_of_the_owner_s_terms_is_asked_once_more_then_bid_farewell(refusing):
    terms = Terms()

    first = move(LIMIT, OPENING, terms, says(price=7600, **refusing), False)
    assert (first.kind, first.price, len(first.refused)) == ("settle", 7600, 1)  # the price talk goes on beside it

    assert move(LIMIT, OPENING, terms, says(**refusing), False).kind == "farewell"


def test_a_red_flag_or_a_sold_watch_ends_it_without_a_word():
    assert move(LIMIT, OPENING, Terms(), says(red_flags=["payment_or_contact_outside_kleinanzeigen"]), False).kind == "end"
    assert move(LIMIT, OPENING, Terms(), says(ended=True), False).kind == "end"


def test_all_is_agreed_once_the_id_card_is_shown_not_only_promised():
    terms = Terms(price=OPENING, bank_transfer=True, delivery="shipping", contract=True)

    assert move(LIMIT, OPENING, terms, says(id_card=True), pictures=False).kind == "settle"
    assert move(LIMIT, OPENING, terms, says(id_card=True), pictures=True) == Move("done", OPENING, "all agreed")
