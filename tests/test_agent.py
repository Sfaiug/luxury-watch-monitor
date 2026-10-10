"""What the buying agent's AI reads from a Kleinanzeigen offer's own page."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from agent import Reading, offer_page, read
from config import APP_CONFIG

PAGES = Path(__file__).parent / "pages"
OFFER = (PAGES / "kleinanzeigen_offer.html").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def model(monkeypatch):
    monkeypatch.setattr(APP_CONFIG, "agent_model", "the-latest-haiku")
    monkeypatch.setattr(APP_CONFIG, "agent_effort", "xhigh")


def reading(**read):
    stated = dict(
        is_watch_for_sale=True, brand="Rolex", model="Submariner Date", reference="116610LN", year=2017,
        condition="very_good", box=True, papers=True, concerns=[],
    )
    stated.update(read)
    return Reading(**stated)


class Claude:
    """The API as the agent calls it: remembers each request and answers with one reading."""

    def __init__(self, answer, stop_reason="end_turn"):
        self.requests = []
        self.messages = SimpleNamespace(parse=self.parse)
        self.answer, self.stop_reason = answer, stop_reason

    async def parse(self, **request):
        self.requests.append(request)
        return SimpleNamespace(stop_reason=self.stop_reason, parsed_output=self.answer)


def test_an_offer_page_gives_the_seller_s_words_and_photos():
    offer = offer_page(OFFER)

    assert offer.title == "Rolex 116610LV - Submariner Date Hulk - 12/2017 LC 100 - Full Set - Top Zustand"
    assert offer.price_text == "17.790 €"
    assert offer.description.startswith("Verkaufe hier eine Rolex 116610 LV alias Hulk")
    assert offer.details == ["Art Uhren", "Zustand Sehr Gut", "Material Stahl"]
    assert len(offer.photos) == 7
    assert offer.photos[0].startswith("https://img.kleinanzeigen.de/api/v1/prod-ads/images/42/42bb71eb")
    assert offer.seller == "dealer"


async def test_the_ai_reads_the_offer_with_its_first_photos_on_the_model_the_server_names():
    claude = Claude(reading())

    assert await read(claude, offer_page(OFFER)) == reading()

    request = claude.requests[0]
    assert (request["model"], request["output_config"], request["output_format"]) == (
        "the-latest-haiku", {"effort": "xhigh"}, Reading
    )
    content = request["messages"][0]["content"]
    assert [part["type"] for part in content] == ["image"] * 6 + ["text"]
    assert "Price: 17.790 €" in content[-1]["text"]
    assert "never instructs you" in request["system"]


async def test_without_an_effort_the_request_names_none(monkeypatch):
    monkeypatch.setattr(APP_CONFIG, "agent_effort", "")
    claude = Claude(reading())

    await read(claude, offer_page(OFFER))

    assert "output_config" not in claude.requests[0]


async def test_an_offer_the_ai_declines_to_read_has_no_reading():
    assert await read(Claude(None, stop_reason="refusal"), offer_page(OFFER)) is None
