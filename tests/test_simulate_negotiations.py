"""The AI sellers the agent is tried against, and the conversation with one as the agent's message box."""

import asyncio
import json

import httpx2
from anthropic import AsyncAnthropic

from negotiation import CHOICES
from scripts import simulate_negotiations as simulating


class Claude(AsyncAnthropic):
    """The AI: gives the answers, in turn, whatever it is asked."""

    def __init__(self, answers):
        super().__init__(api_key="test", max_retries=0, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(self.answer)))
        self.answers = list(answers)

    def answer(self, request):
        text = json.dumps(self.answers.pop(0))
        return httpx2.Response(200, json={"id": "m", "type": "message", "role": "assistant", "model": "m", "stop_reason": "end_turn",
                                          "usage": {"input_tokens": 1, "output_tokens": 1}, "content": [{"type": "text", "text": text}]})


def read(**said):
    return {"price": None, "accepts_offer": False, "turns_down": False, "bank_transfer": None, "delivery": None, "contract": None,
            "id_card": None, "ended": False, "red_flags": [], "question": None, **said}


def test_every_seller_is_briefed_to_an_end_and_the_owner_s_word():
    assert all(seller.ends in ("agreed", "ended") and seller.choice in CHOICES for seller in simulating.SELLERS.values())


def test_the_agent_talks_with_the_ai_seller_until_it_ends_and_the_end_is_held_to_the_brief():
    sold = simulating.SELLERS["sold"]
    claude = Claude([{"message": "Hallo, ist die Uhr noch zu haben?"},  # the agent's first message
                     {"message": "Leider schon gestern verkauft.", "picture": False},  # the seller's answer
                     read(ended=True)])  # the agent's reading of it

    negotiation, said, heard = asyncio.run(simulating.simulate("sold", sold, claude))

    assert [(m.outbound, m.text) for m in said] == [(True, "Hallo, ist die Uhr noch zu haben?"),
                                                    (False, "Leider schon gestern verkauft.")]
    assert negotiation.status == "ended" and heard == [] and claude.answers == []
    assert simulating.report("sold", sold, negotiation, said, heard).splitlines() == [
        "=== sold: ended (the seller ended it), as briefed",
        "Buyer : Hallo, ist die Uhr noch zu haben?",
        "Seller: Leider schon gestern verkauft."]
    briefed_otherwise = simulating.Seller("", "agreed")
    assert simulating.report("sold", briefed_otherwise, negotiation, said, heard).startswith(
        "=== sold: ended (the seller ended it), BRIEFED TO END agreed")
