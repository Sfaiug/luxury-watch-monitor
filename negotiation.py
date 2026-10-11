"""What the buying agent answers a Kleinanzeigen seller, by the owner's terms, until the whole purchase is agreed.

The owner's terms (owner rules, 11 Oct 2026): a price within the limit,
payment by bank transfer only, insured shipping or else pickup, and the
seller's agreement to a purchase contract (Kaufvertrag) with a picture of
their ID card. Only then does the owner hear of it, to send the contract
and pay. The AI reads where the seller stands; what to offer, when to stop
and when all is agreed are decided here, in code.
"""

from dataclasses import dataclass, field
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from agent import STEP, RedFlag, flagged
from prices_page import euros

CLOSE = 0.02  # a seller asking this share or less above the offer is met at their price


class SellerSays(BaseModel):
    """Where the seller stands after their latest messages, as the AI reads it."""

    price: Optional[int]
    accepts_offer: bool
    bank_transfer: Optional[bool]
    delivery: Optional[Literal["shipping", "pickup"]]
    contract: Optional[bool]
    id_card: Optional[bool]
    ended: bool
    red_flags: List[RedFlag] = Field(default_factory=list)
    question: Optional[str]


@dataclass
class Terms:
    """What the seller has agreed so far."""

    price: Optional[int] = None
    bank_transfer: bool = False
    delivery: Optional[str] = None
    contract: bool = False
    id_card: bool = False
    asked_again: List[str] = field(default_factory=list)  # terms the seller refused once and was asked again

    def open(self) -> List[str]:
        return [
            name
            for name, settled in (
                ("payment by bank transfer", self.bank_transfer),
                ("insured shipping, or else pickup", self.delivery),
                ("the purchase contract", self.contract),
                ("a picture of the seller's ID card", self.id_card),
            )
            if not settled
        ]


@dataclass
class Move:
    """The agent's answer: an offer, its final offer (the limit), settling the rest of an agreed price, done,
    a farewell, or the end without a word."""

    kind: str
    price: Optional[int] = None
    why: str = ""
    refused: List[str] = field(default_factory=list)  # terms the seller refuses, to be asked again


def move(limit: int, offered: int, terms: Terms, says: SellerSays, pictures: bool) -> Move:
    """The answer to where the seller stands, by the owner's terms; `terms` takes in what the seller agreed.

    `pictures`: the seller sent pictures since the agent last wrote.
    """
    if says.red_flags:
        return Move("end", why=flagged(says.red_flags))
    if says.ended:
        return Move("end", why="the seller ended it")
    refused = [
        name
        for name, given in (("bank transfer", says.bank_transfer), ("the purchase contract", says.contract),
                            ("a picture of the ID card", says.id_card))
        if given is False
    ]
    if any(name in terms.asked_again for name in refused):
        return Move("farewell", why="the seller refuses " + " and ".join(refused))
    terms.asked_again += refused
    # A refusal takes back what was agreed; the ID card counts once said and shown
    terms.bank_transfer = terms.bank_transfer if says.bank_transfer is None else says.bank_transfer
    terms.delivery = says.delivery or terms.delivery
    terms.contract = terms.contract if says.contract is None else says.contract
    terms.id_card = terms.id_card if says.id_card is None else says.id_card and (pictures or terms.id_card)

    answer = _price(limit, offered, terms, says.price, says.accepts_offer)
    answer.refused = refused
    return answer


def _price(limit: int, offered: int, terms: Terms, asked: Optional[int], accepts_offer: bool) -> Move:
    if terms.price is None:
        if accepts_offer:
            terms.price = offered
        elif asked is not None and (asked <= offered or (asked <= limit and asked - offered <= max(STEP, asked * CLOSE))):
            terms.price = min(asked, limit)
        elif asked is not None:
            if offered >= limit:
                return Move("farewell", why=f"the seller asks {euros(asked)}, above the limit of {euros(limit)}")
            # Half the room left up to the limit, and no more than halfway towards the seller, 50 euros at a time
            counter = max(offered + STEP, (offered + min(limit - offered, asked - offered) // 2) // STEP * STEP)
            if counter >= limit - STEP:  # the last step is the limit itself, or the seller's price below it
                return Move("final", min(limit, asked), f"the seller asks {euros(asked)}")
            return Move("offer", counter, f"the seller asks {euros(asked)}")
        else:
            return Move("offer", offered, "the seller names no price")
    if terms.open():
        return Move("settle", terms.price, "open: " + ", ".join(terms.open()))
    return Move("done", terms.price, "all agreed")
