"""Data models for watch monitor application."""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional, List, Dict, Any
from urllib.parse import urlsplit

from config import APP_CONFIG


@dataclass
class WatchData:
    """Represents a single watch listing."""

    # Required fields
    title: str
    url: str
    site_name: str
    site_key: str

    # Optional fields with defaults
    brand: Optional[str] = None
    model: Optional[str] = None
    reference: Optional[str] = None
    year: Optional[str] = None
    price: Optional[Decimal] = None
    currency: str = "EUR"
    price_display: Optional[str] = None
    image_url: Optional[str] = None
    image_urls: List[str] = field(default_factory=list)

    # Condition and accessories
    condition: Optional[str] = None
    has_papers: Optional[bool] = None
    has_box: Optional[bool] = None

    # Physical attributes
    case_material: Optional[str] = None
    diameter: Optional[str] = None

    # Metadata
    scraped_at: datetime = field(default_factory=datetime.now)
    detail_scraped: bool = False

    # Internal fields (not for display)
    _composite_id: Optional[str] = field(default=None, init=False)
    _former_id: Optional[str] = field(default=None, init=False)
    _price_for_hash: Optional[str] = field(default=None, init=False)

    def __post_init__(self):
        """Clean and validate data after initialization."""
        # Clean text fields
        self.title = self._clean_text(self.title)
        if self.brand:
            self.brand = self._clean_text(self.brand)
        if self.model:
            self.model = self._clean_text(self.model)
        if self.reference:
            self.reference = self._clean_text(self.reference)
        self.image_urls = [url for url in self.image_urls if url]
        if self.image_url and self.image_url not in self.image_urls:
            self.image_urls.insert(0, self.image_url)
        if not self.image_url and self.image_urls:
            self.image_url = self.image_urls[0]

        # Format price display
        if self.price and not self.price_display:
            self.price_display = self._format_price_display()

        # Extract price for hashing
        if self.price:
            self._price_for_hash = str(int(self.price * 100))  # Convert to cents

        # Generate composite ID, and the id this listing had before 9 Oct 2026
        self._composite_id = self._generate_composite_id()
        self._former_id = self._generate_former_id()

    @staticmethod
    def _clean_text(text: str) -> str:
        """Clean and normalize text."""
        if not text:
            return ""
        # Remove extra whitespace
        text = re.sub(r"\s+", " ", text).strip()
        # Unescape HTML entities
        import html

        text = html.unescape(text)
        return text

    def _format_price_display(self) -> str:
        """Format price for display."""
        if not self.price:
            return APP_CONFIG.emoji_config["question"]

        # Format with thousands separator
        formatted = f"{self.price:,.0f}".replace(",", ".")

        # Add currency symbol
        if self.currency == "EUR":
            return f"€{formatted}"
        elif self.currency == "USD":
            return f"${formatted}"
        else:
            return f"{formatted} {self.currency}"

    def _generate_composite_id(self) -> str:
        """Shop, the listing's address there and its listed price: the same
        listing is announced once, and again only when its price changes."""
        return f"{self.site_key}:{self.address}:{self._price_for_hash or ''}"

    def _generate_former_id(self) -> str:
        """The id watches were remembered under until 9 Oct 2026: a hash of
        brand, model, reference, price, year and material, or of title, price
        and link where two of the first four were missing. Kept so that a
        watch announced under it stays known."""
        brand_norm = (self.brand or "").lower()
        model_norm = (self.model or "").lower()
        ref_norm = (self.reference or "").lower().replace(" ", "")
        year_norm = str(self.year or "").lower()
        price_norm = self._price_for_hash or ""
        material_norm = (self.case_material or "").lower()

        id_string = "|".join(
            filter(
                None,
                [brand_norm, model_norm, ref_norm, price_norm, year_norm, material_norm],
            )
        )
        if sum(1 for x in [brand_norm, model_norm, ref_norm, price_norm] if x) < 2:
            id_string = "|".join(
                filter(None, [self.title.lower(), price_norm, self.url.lower()])
            )

        return hashlib.md5(id_string.encode("utf-8")).hexdigest()

    @property
    def composite_id(self) -> str:
        """Get the composite ID for duplicate detection."""
        return self._composite_id

    @property
    def address(self) -> str:
        """The listing's address at its shop: the path of its link, the query
        left out, as World of Time's changes with the cards around it."""
        return urlsplit(self.url).path

    @property
    def former_id(self) -> str:
        """The id this listing was remembered under until 9 Oct 2026."""
        return self._former_id

    @property
    def chrono24_search_url(self) -> str:
        """Generate Chrono24 search URL for this watch."""
        # Build search query
        query_parts = []

        if self.brand and self.brand != APP_CONFIG.emoji_config["question"]:
            query_parts.append(self.brand)

        if self.model and self.model != APP_CONFIG.emoji_config["question"]:
            # Avoid duplicating brand in model
            if self.brand and self.model.lower().startswith(self.brand.lower()):
                model_clean = self.model[len(self.brand) :].strip()
                if model_clean:
                    query_parts.append(model_clean)
            else:
                query_parts.append(self.model)

        if self.reference and self.reference != APP_CONFIG.emoji_config["question"]:
            query_parts.append(self.reference)

        # A listing known only by its title is searched by its title
        if not query_parts:
            query_parts.append(self.title)

        import chrono24  # here, since chrono24 reads its pages into WatchData

        return chrono24.search(" ".join(query_parts))

    def to_discord_embed(self, color: int) -> Dict[str, Any]:
        """Convert to Discord embed format."""
        # Build title
        embed_title = self._build_embed_title()

        # Create embed structure
        embed = {
            "title": embed_title,
            "url": self.url,
            "color": color,
            "fields": [],
            "footer": {
                "text": f"{self.site_name} - Detected: {self.scraped_at.strftime('%Y-%m-%d %H:%M:%S')}"
            },
        }

        # Add image if available
        if self.image_url:
            embed["image"] = {"url": self.image_url}

        # Add price field
        price_display = self.price_display or APP_CONFIG.emoji_config["question"]
        embed["fields"].append(
            {
                "name": f"{APP_CONFIG.emoji_config['price']} Price:",
                "value": f"**{price_display}**",
                "inline": False,
            }
        )

        # Add reference if available and not in title
        if (
            self.reference
            and self.reference != APP_CONFIG.emoji_config["question"]
            and self.reference not in embed_title
        ):
            embed["fields"].append(
                {
                    "name": f"{APP_CONFIG.emoji_config['reference']} Reference:",
                    "value": f"**{self.reference}**",
                    "inline": False,
                }
            )

        # Add Chrono24 search link
        embed["fields"].append(
            {
                "name": f"{APP_CONFIG.emoji_config['search']} Chrono24 Search:",
                "value": f"[**Search similar**]({self.chrono24_search_url})",
                "inline": False,
            }
        )

        # Add bottom fields
        embed["fields"].append({"name": "\u200b", "value": "\u200b", "inline": False})

        # Add optional fields
        bottom_fields = []

        if self.year and self.year != APP_CONFIG.emoji_config["question"]:
            bottom_fields.append(
                {
                    "name": f"{APP_CONFIG.emoji_config['year']} Year:",
                    "value": f"**{self.year}**",
                    "inline": True,
                }
            )

        if self.condition and self.condition != APP_CONFIG.emoji_config["question"]:
            bottom_fields.append(
                {
                    "name": f"{APP_CONFIG.emoji_config['condition']} Condition:",
                    "value": f"**{self.condition}**",
                    "inline": True,
                }
            )

        if self.has_box is not None:
            box_emoji = (
                APP_CONFIG.emoji_config["check"]
                if self.has_box
                else APP_CONFIG.emoji_config["cross"]
            )
            bottom_fields.append(
                {
                    "name": f"{APP_CONFIG.emoji_config['box']} Box:",
                    "value": f"**{box_emoji}**",
                    "inline": True,
                }
            )

        if self.has_papers is not None:
            papers_emoji = (
                APP_CONFIG.emoji_config["check"]
                if self.has_papers
                else APP_CONFIG.emoji_config["cross"]
            )
            bottom_fields.append(
                {
                    "name": f"{APP_CONFIG.emoji_config['papers']} Papers:",
                    "value": f"**{papers_emoji}**",
                    "inline": True,
                }
            )

        if (
            self.case_material
            and self.case_material != APP_CONFIG.emoji_config["question"]
        ):
            bottom_fields.append(
                {
                    "name": f"{APP_CONFIG.emoji_config['material']} Case Material:",
                    "value": f"**{self.case_material}**",
                    "inline": True,
                }
            )

        if self.diameter and self.diameter != APP_CONFIG.emoji_config["question"]:
            bottom_fields.append(
                {
                    "name": f"{APP_CONFIG.emoji_config['diameter']} Diameter:",
                    "value": f"**{self.diameter}**",
                    "inline": True,
                }
            )

        embed["fields"].extend(bottom_fields)

        return embed

    def _build_embed_title(self) -> str:
        """Build a clean title for Discord embed."""
        parts = []

        # Add brand
        if self.brand and self.brand != APP_CONFIG.emoji_config["question"]:
            parts.append(self.brand)

        # Add model (avoiding duplication with brand)
        if self.model and self.model != APP_CONFIG.emoji_config["question"]:
            if self.brand and self.model.lower().startswith(self.brand.lower()):
                model_clean = self.model[len(self.brand) :].strip()
                if model_clean:
                    parts.append(model_clean)
            else:
                parts.append(self.model)

        # A listing known only by its title is announced by its title
        if not parts:
            parts = [self.title]

        embed_title = " ".join(parts)

        # Add reference if not already in title
        if (
            self.reference
            and self.reference != APP_CONFIG.emoji_config["question"]
            and self.reference not in embed_title
        ):
            embed_title += f" | {self.reference}"

        # Truncate if too long
        if len(embed_title) > 250:
            embed_title = embed_title[:250] + "..."

        return embed_title or "Unknown Watch"


@dataclass
class ScrapingSession:
    """Represents a single scraping session with statistics."""

    session_id: str = field(
        default_factory=lambda: datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    started_at: datetime = field(default_factory=datetime.now)
    ended_at: Optional[datetime] = None

    # Statistics
    sites_scraped: int = 0
    total_watches_found: int = 0
    total_new_watches: int = 0
    notifications_sent: int = 0
    errors_encountered: int = 0

    # Memory tracking
    memory_usage_start_mb: Optional[float] = None
    memory_usage_end_mb: Optional[float] = None
    memory_delta_mb: Optional[float] = None

    # Per-site statistics
    site_stats: Dict[str, Dict[str, int]] = field(default_factory=dict)

    def add_site_result(
        self,
        site_key: str,
        total_found: int,
        new_found: int,
        notifications: int,
        errors: int = 0,
    ):
        """Add results for a single site."""
        self.sites_scraped += 1
        self.total_watches_found += total_found
        self.total_new_watches += new_found
        self.notifications_sent += notifications
        self.errors_encountered += errors

        self.site_stats[site_key] = {
            "total_found": total_found,
            "new_found": new_found,
            "notifications_sent": notifications,
            "errors": errors,
        }

    def finalize(self):
        """Mark session as complete."""
        self.ended_at = datetime.now()

    @property
    def duration_seconds(self) -> Optional[float]:
        """Get session duration in seconds."""
        if self.ended_at:
            return (self.ended_at - self.started_at).total_seconds()
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "session_id": self.session_id,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "duration_seconds": self.duration_seconds,
            "sites_scraped": self.sites_scraped,
            "total_watches_found": self.total_watches_found,
            "total_new_watches": self.total_new_watches,
            "notifications_sent": self.notifications_sent,
            "errors_encountered": self.errors_encountered,
            "memory_usage_start_mb": self.memory_usage_start_mb,
            "memory_usage_end_mb": self.memory_usage_end_mb,
            "memory_delta_mb": self.memory_delta_mb,
            "site_stats": self.site_stats,
        }
