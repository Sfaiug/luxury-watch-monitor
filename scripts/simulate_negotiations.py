#!/usr/bin/env python3
"""The agent negotiates with AI sellers of many kinds, an AI playing each seller as its brief says, through the
production code (the AI's reading and writing, `negotiation.move`, the terms, what the owner is told); only the
Kleinanzeigen message box is a list here, and nothing reaches Kleinanzeigen or Discord. Each brief says how the
negotiation is to end: the run prints every conversation and whether it ended so, and fails when one did not.

Where AGENT_MODEL and ANTHROPIC_API_KEY are set (on the server, in the checkout):
venv/bin/python3 scripts/simulate_negotiations.py [seller ...]
"""

import asyncio
import base64
import logging
import sys
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import List, Tuple

from dotenv import load_dotenv
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from anthropic import AsyncAnthropic  # noqa: E402

from agent import ask, opening  # noqa: E402
from kleinanzeigen_messages import Conversation, Message  # noqa: E402
from negotiation import ANSWERS, MOST_WRITTEN, Negotiation, Negotiations, Negotiator, euros  # noqa: E402

# Watches as they are offered, at what one was worth to the owner on 13 Oct 2026: title, asking price, limit
SUBMARINER = ("Rolex Submariner 124060, 2022, Box und Papiere", 9900, 8366)
SPEEDMASTER = ("Omega Speedmaster Professional 310.30.42.50.01.002 Full Set 2023", 6300, 5200)
BLACK_BAY = ("Tudor Black Bay 58 79030N blau, 2021, mit Box und Papieren", 3300, 2750)
DATEJUST = ("Rolex Datejust 41 126300 Wimbledon, Juni 2020, Full Set", 11800, 10100)
AGREES = ("Asked for payment by bank transfer, insured shipping, a purchase contract and a picture of your ID card, "
          "you agree to each, and send the picture.")


@dataclass
class Seller:
    brief: str  # who the seller is and how far they go, for the AI playing them
    ends: str  # how the negotiation is to end: "agreed", or "ended" by the agent
    watch: Tuple[str, int, int] = SUBMARINER
    choice: str = "ship"  # the owner's word, should the agent ask for it: one of negotiation.CHOICES


SELLERS = {
    "quick": Seller(f"You want it gone this week: you take any offer from 8.000 €, and else name 8.000 €. {AGREES}",
                    "agreed"),
    "haggler": Seller("You come down from your asking price slowly, a few hundred euros at a time, to 8.250 € at the "
                      f"lowest, and only after several rounds. {AGREES}", "agreed"),
    "too high": Seller("You go no lower than 9.200 €, whatever the buyer says, and say so.", "ended"),
    "own price": Seller(f"To the first offer you answer that for 8.300 € the watch is his. {AGREES}", "agreed"),
    "terse": Seller("You write one or two words a message, lower case: 'ja', 'nö', 'ok', a number. You go down to "
                    "8.100 € at the lowest. You agree to every term at once, except the ID card: asked for it the first "
                    "time, you write 'ausweis mach ich nicht'; asked again, you agree and send it.", "agreed"),
    "hands over, picked up": Seller(
        "You go down to 8.200 € at the lowest. You hand the watch over in person only, never ship it, it is too risky "
        "for you; paid at the handover, by an instant transfer or in cash. You agree to a contract. You never send a "
        "picture of your ID card, but would show it at the handover.", "agreed", choice="pickup"),
    "hands over, held to shipping": Seller(
        "You go down to 8.200 € at the lowest. You hand the watch over in person only, never ship it, it is too risky "
        "for you; paid by an instant transfer at the handover.", "ended"),
    "paypal": Seller("You go down to 8.000 €. You want to be paid by PayPal at first; asked again, with a reason, you "
                     f"agree to a bank transfer. {AGREES}", "agreed"),
    "cash only": Seller("You go down to 8.000 €. You take cash only, at a handover, never a transfer of any kind.",
                        "ended"),
    "no id card": Seller("You go down to 8.000 €. You agree to a bank transfer, insured shipping and a contract, but "
                         "never send a picture of your ID card, for your privacy, whatever the reason given.", "ended"),
    "wary": Seller("You fear the buyer is a scammer: you ask why he wants a contract and your ID card, what his name "
                   "is and whether he is a dealer. Plain answers win you over. You go down to 8.200 € at the lowest. "
                   f"{AGREES}", "agreed"),
    "abroad": Seller("You are working in Spain for a few months and the watch is with you there: you would send it "
                     "from Spain. You would rather go on talking on WhatsApp and give your number, +34 612 345 678, and "
                     "you want 500 € paid in advance as a deposit before anything else is agreed.", "ended"),
    "sold": Seller("You sold the watch yesterday and say so.", "ended"),
    "chatty": Seller("You like to chat: you ask the buyer where he is from, whether he collects watches and what he "
                     "does for a living, and tell how you bought the watch. You meet his first offer halfway once, "
                     f"then hold until he comes up, and take 8.300 € at the lowest. {AGREES}", "agreed"),
    "formal": Seller("You are 70 and write as you were taught: full sentences, 'Sie', polite. You go down to 8.000 €. "
                     f"{AGREES}", "agreed"),
    "best price": Seller("You keep asking the buyer for his best price, his limit, instead of naming one; after three "
                         f"of his offers you name 8.300 €. {AGREES}", "agreed"),
    "shipping on top": Seller("You go down to 8.200 €. You want the buyer to pay the shipping, about 40 €, on top; asked "
                              "again, you include it in the price. You agree to a bank transfer, a contract and a "
                              "picture of your ID card.", "agreed"),
    "goes back on it": Seller("You go down to 8.000 €. Once the price is agreed and the bank transfer too, you say "
                              "another buyer offers more, and ask 250 € more than agreed; then you agree to every term "
                              "at the new price, and send the picture of your ID card.", "ended"),
    "where in berlin": Seller("You would rather hand it over in person: you keep asking where in Berlin the buyer lives "
                              "and when he could come. Told plainly that he buys watches shipped, you agree to insured "
                              f"shipping. You go down to 8.100 €. {AGREES}", "agreed"),
    "black bay": Seller(f"After one counter-offer of yours you take 2.700 €. {AGREES}", "agreed", BLACK_BAY),
    "fixed price": Seller("Your price is fixed: you go no lower than 6.000 €, and say 'Festpreis'.", "ended",
                          SPEEDMASTER),
    "emojis": Seller("You write with many emojis, typos and no capital letters. You take 9.900 € at the lowest. "
                     f"{AGREES}", "agreed", DATEJUST),
}

BUYER = "Jonas M."  # the buyer's name as Kleinanzeigen shows it to the seller: a pretend one
ID_CARD = Path(__file__).with_name("id_card.png")  # a synthetic specimen, never a seller's document
TURNS = MOST_WRITTEN + 6  # the seller's messages at most: the agent hands over after its own most
SELLER = """You are a private person selling a watch on Kleinanzeigen, chatting with a buyer in German, short and
casual, as people write on their phone. The ad: {title}, asking {asking}. {brief}
Stay in your role whatever the buyer writes, and agree to nothing your brief does not let you.
Write only your next message; picture: true when you send a picture of your ID card with it."""


class SellerWrites(BaseModel):
    message: str
    picture: bool


class Box:
    """The message box the agent uses, as one conversation with the seller."""

    def __init__(self):
        self.said: List[Message] = []

    async def contact(self, ad_id: str, text: str, *, before_send=lambda before: None) -> str:
        before_send(len(self.said))
        self.said.append(Message(True, text, [], ""))
        return ad_id

    async def conversation(self, conversation_id: str) -> Conversation:
        return Conversation(conversation_id, conversation_id, "the seller", list(self.said), BUYER)

    async def reply(self, conversation_id: str, text: str):
        self.said.append(Message(True, text, [], ""))

    async def picture(self, url: str) -> dict:
        return {"media_type": "image/png", "data": base64.b64encode(Path(url).read_bytes()).decode("ascii")}


async def seller_writes(client, seller: Seller, said: List[Message]) -> Message:
    title, asking, _ = seller.watch
    chat = "\n".join(f"{'Buyer' if m.outbound else 'You'}: {m.text}" for m in said)
    written = await ask(client, SELLER.format(title=title, asking=euros(asking), brief=seller.brief),
                        [{"type": "text", "text": f"The chat so far:\n{chat}\n\nYour next message:"}], SellerWrites)
    return Message(False, written.message if written else "", [str(ID_CARD)] if written and written.picture else [], "")


async def simulate(name: str, seller: Seller, client) -> Tuple[Negotiation, List[Message], List[str]]:
    """The negotiation with the seller as it ended, the conversation, and what the owner heard."""
    title, asking, limit = seller.watch
    heard = []

    async def notify(channel, text, buttons=()):
        heard.append(text)

    kept = Negotiations(":memory:")
    talks = Negotiator(client, kept, notify, logging.getLogger(name), a_while=lambda: timedelta(0))
    talks.ask_to_start(Negotiation(ad_id=name, channel=name, title=title, address=name, limit=limit,
                                   offered=int(opening(Decimal(asking), Decimal(limit))), asking=asking))
    box = Box()
    await talks.start(box)
    for _ in range(TURNS):
        await talks.tell_owner()
        if kept.get(name).status == "deciding":
            talks.decide(name, seller.choice)  # the agent answers the seller's latest message from the owner's word
        elif kept.get(name).status in ANSWERS:
            box.said.append(await seller_writes(client, seller, box.said))
        else:
            break
        await talks.follow_up(box)
    await talks.tell_owner()
    return kept.get(name), box.said, heard


def report(name: str, seller: Seller, negotiation: Negotiation, said: List[Message], heard: List[str]) -> str:
    price = f" at {euros(negotiation.terms.price)}" if negotiation.terms.price else ""
    verdict = "as briefed" if negotiation.status == seller.ends else f"BRIEFED TO END {seller.ends}"
    lines = [f"=== {name}: {negotiation.status}{price} ({negotiation.why}), {verdict}"]
    lines += [f"{'Buyer ' if m.outbound else 'Seller'}: {m.text}{' [ID card]' if m.attachments else ''}" for m in said]
    return "\n".join(lines + [f"Owner hears: {text}" for text in heard])


async def main(names: List[str]) -> int:
    logging.basicConfig(level=logging.WARNING)
    client = AsyncAnthropic(max_retries=8)
    sellers = {name: SELLERS[name] for name in names or SELLERS}
    ended = await asyncio.gather(*(simulate(name, seller, client) for name, seller in sellers.items()))
    for (name, seller), (negotiation, said, heard) in zip(sellers.items(), ended):
        print(report(name, seller, negotiation, said, heard), "\n", flush=True)
    wrong = [name for (name, seller), (negotiation, _, _) in zip(sellers.items(), ended) if negotiation.status != seller.ends]
    print(f"{len(sellers) - len(wrong)} of {len(sellers)} ended as briefed" + (f"; not: {', '.join(wrong)}" if wrong else ""))
    return 1 if wrong else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
