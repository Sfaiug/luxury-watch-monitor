"""Members' filters: a search on a marketplace whose matches go to a channel of its own."""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Type

from config import SiteConfig
from scrapers import kleinanzeigen
from scrapers.base import BaseScraper


@dataclass(frozen=True)
class Store:
    """A marketplace a filter can search."""

    name: str
    color: int
    base_url: str
    scraper: Type[BaseScraper]
    search_url: Callable[..., str]


STORES: Dict[str, Store] = {
    "kleinanzeigen": Store(
        name="Kleinanzeigen",
        color=0x86B817,
        base_url=kleinanzeigen.BASE_URL,
        scraper=kleinanzeigen.KleinanzeigenScraper,
        search_url=kleinanzeigen.search_url,
    ),
}


@dataclass(frozen=True)
class Filter:
    """One member's search. Its channel is where its matches go and what it is known by."""

    channel_id: str
    user_id: str
    store: str
    seller: str
    words: str
    min_price: Optional[int] = None
    max_price: Optional[int] = None
    conditions: List[str] = field(default_factory=list)  # none: any condition

    @property
    def key(self) -> str:
        return f"filter:{self.channel_id}"

    @property
    def search_url(self) -> str:
        return STORES[self.store].search_url(
            self.words, self.min_price, self.max_price, self.seller, self.conditions
        )

    def scraper(self, session, logger) -> BaseScraper:
        """The filter as the monitor sees it: one more site to scan."""
        store = STORES[self.store]
        source = SiteConfig(
            name=store.name,
            key=self.key,
            url=self.search_url,
            webhook_env_var="",
            color=store.color,
            base_url=store.base_url,
            channel_id=self.channel_id,
        )
        return store.scraper(source, session, logger)


class FilterStore:
    """The filters, kept in one JSON file."""

    def __init__(self, path: str):
        self.path = Path(path)

    def all(self) -> List[Filter]:
        if not self.path.exists():
            return []
        entries = json.loads(self.path.read_text(encoding="utf-8"))
        return [Filter(**entry) for entry in entries]

    def add(self, new: Filter):
        self._write(self.all() + [new])

    def remove(self, channel_id: str):
        self._write([f for f in self.all() if f.channel_id != channel_id])

    def _write(self, filters: List[Filter]):
        # Written beside the file and moved over it, so a crash leaves the old file whole
        beside = self.path.with_name(self.path.name + ".tmp")
        beside.write_text(
            json.dumps([asdict(f) for f in filters], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        beside.replace(self.path)
