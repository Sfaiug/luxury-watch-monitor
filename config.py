"""Configuration management for watch monitor application."""

import os
from dataclasses import dataclass, field
from typing import Dict, Optional


def _env_bool(name: str, default: str = "false") -> bool:
    """Parse common boolean environment values."""
    return os.getenv(name, default).lower() in ("true", "1", "yes", "on")


@dataclass
class SiteConfig:
    """Configuration for a single watch retailer site."""

    name: str
    key: str
    url: str
    webhook_env_var: str
    color: int
    base_url: str
    channel_env_var: Optional[str] = None

    # Selectors for scraping (to be customized per site)
    watch_container_selector: str = ""
    title_selector: str = ""
    price_selector: str = ""
    link_selector: str = ""
    image_selector: str = ""

    # Additional configuration
    detail_page_selectors: Dict[str, str] = field(default_factory=dict)
    known_brands: Dict[str, str] = field(default_factory=dict)
    condition_mappings: Dict[str, str] = field(default_factory=dict)

    @property
    def webhook_url(self) -> Optional[str]:
        """Get webhook URL from environment variable."""
        return os.environ.get(self.webhook_env_var)

    @property
    def discord_channel_id(self) -> Optional[str]:
        """Get the bot target channel for this site when bot delivery is enabled."""
        env_var = self.channel_env_var
        if env_var and os.environ.get(env_var):
            return os.environ.get(env_var)

        inferred = self.webhook_env_var.replace("_WEBHOOK_URL", "_CHANNEL_ID")
        return os.environ.get(inferred)


@dataclass
class AppConfig:
    """Application-wide configuration."""

    # Persistence
    seen_watches_file: str = os.getenv("SEEN_WATCHES_FILE", "seen_watches.json")
    session_history_file: str = os.getenv(
        "SESSION_HISTORY_FILE", "session_history.json"
    )

    # Monitoring - PRODUCTION SAFE DEFAULTS
    check_interval_seconds: int = int(
        os.getenv("CHECK_INTERVAL_SECONDS", "180")
    )  # 3 minutes default
    max_concurrent_scrapers: int = int(
        os.getenv("MAX_CONCURRENT_SCRAPERS", "2")
    )  # Conservative default
    max_concurrent_details: int = int(
        os.getenv("MAX_CONCURRENT_DETAILS", "5")
    )  # Moderate concurrency

    # HTTP settings
    user_agent: str = os.getenv(
        "USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
    )
    request_timeout: int = int(
        os.getenv("REQUEST_TIMEOUT", "15")
    )  # More conservative timeout
    detail_page_delay: float = float(
        os.getenv("DETAIL_PAGE_DELAY", "1.5")
    )  # Slightly longer delay

    # Retry settings
    max_retries: int = int(os.getenv("MAX_RETRIES", "3"))
    retry_backoff_factor: float = float(os.getenv("RETRY_BACKOFF_FACTOR", "2.0"))

    # Exchange rate settings
    exchange_rate_api_url: str = os.getenv(
        "EXCHANGE_RATE_API_URL", "https://api.exchangerate-api.com/v4/latest/USD"
    )
    exchange_rate_cache_duration: int = int(
        os.getenv("EXCHANGE_RATE_CACHE_DURATION", "3600")
    )

    # Data retention
    max_seen_items_per_site: int = int(os.getenv("MAX_SEEN_ITEMS_PER_SITE", "1000"))
    session_history_retention_days: int = int(
        os.getenv("SESSION_HISTORY_RETENTION_DAYS", "30")
    )

    # Memory management
    memory_warning_threshold_mb: int = int(
        os.getenv("MEMORY_WARNING_THRESHOLD_MB", "400")
    )
    memory_critical_threshold_mb: int = int(
        os.getenv("MEMORY_CRITICAL_THRESHOLD_MB", "500")
    )
    force_gc_every_n_cycles: int = int(os.getenv("FORCE_GC_EVERY_N_CYCLES", "3"))
    max_session_history_entries: int = int(
        os.getenv("MAX_SESSION_HISTORY_ENTRIES", "100")
    )

    # Feature flags
    enable_notifications: bool = os.getenv("ENABLE_NOTIFICATIONS", "true").lower() in (
        "true",
        "1",
        "yes",
    )
    enable_detail_scraping: bool = os.getenv(
        "ENABLE_DETAIL_SCRAPING", "true"
    ).lower() in ("true", "1", "yes")
    enable_exchange_rate_conversion: bool = os.getenv(
        "ENABLE_EXCHANGE_RATE_CONVERSION", "true"
    ).lower() in ("true", "1", "yes")

    # MUV / Discord interaction actions
    enable_muv_actions: bool = _env_bool("ENABLE_MUV_ACTIONS", "false")
    action_store_file: str = os.getenv("ACTION_STORE_FILE", "muv_actions.sqlite3")
    discord_interactions_enabled: bool = _env_bool(
        "DISCORD_INTERACTIONS_ENABLED", "false"
    )
    discord_interactions_host: str = os.getenv("DISCORD_INTERACTIONS_HOST", "0.0.0.0")
    discord_interactions_port: int = int(os.getenv("DISCORD_INTERACTIONS_PORT", "8080"))
    discord_interactions_path: str = os.getenv(
        "DISCORD_INTERACTIONS_PATH", "/discord/interactions"
    )
    discord_public_key: str = os.getenv("DISCORD_PUBLIC_KEY", "")
    discord_bot_token: str = os.getenv("DISCORD_BOT_TOKEN", "")
    discord_api_base_url: str = os.getenv(
        "DISCORD_API_BASE_URL", "https://discord.com/api/v10"
    )
    discord_alert_channel_id: str = os.getenv("DISCORD_ALERT_CHANNEL_ID", "")
    action_token_secret: str = os.getenv("ACTION_TOKEN_SECRET", "")
    muv_http_actions_enabled: bool = _env_bool("MUV_HTTP_ACTIONS_ENABLED", "false")
    muv_action_base_url: str = os.getenv("MUV_ACTION_BASE_URL", "")
    muv_action_web_path: str = os.getenv("MUV_ACTION_WEB_PATH", "/muv/actions")
    muv_offer_webhook_path: str = os.getenv("MUV_OFFER_WEBHOOK_PATH", "/muv/offers")
    muv_offer_link_urls: str = os.getenv("MUV_OFFER_LINK_URLS", "")
    muv_offer_link_poll_seconds: int = int(
        os.getenv("MUV_OFFER_LINK_POLL_SECONDS", "900")
    )
    muv_result_webhook_url: str = os.getenv("MUV_RESULT_WEBHOOK_URL", "")
    muv_base_url: str = os.getenv("MUV_BASE_URL", "https://www.meineuhrverkaufen.de")
    muv_submission_mode: str = os.getenv("MUV_SUBMISSION_MODE", "prepare")
    muv_action_label: str = os.getenv("MUV_ACTION_LABEL", "Send to MUV")
    muv_auto_submit: bool = _env_bool("MUV_AUTO_SUBMIT", "false")
    muv_match_threshold: float = float(os.getenv("MUV_MATCH_THRESHOLD", "0.72"))
    muv_min_picture_count: int = int(os.getenv("MUV_MIN_PICTURE_COUNT", "3"))
    muv_default_condition: int = int(os.getenv("MUV_DEFAULT_CONDITION", "3"))  # Good
    muv_seller_email: str = os.getenv("MUV_SELLER_EMAIL", "")
    muv_seller_first_name: str = os.getenv("MUV_SELLER_FIRST_NAME", "")
    muv_seller_last_name: str = os.getenv("MUV_SELLER_LAST_NAME", "")
    muv_accept_terms: bool = _env_bool("MUV_ACCEPT_TERMS", "false")
    muv_confirm_eu_seller: bool = _env_bool("MUV_CONFIRM_EU_SELLER", "false")

    # Emojis for Discord embeds
    emoji_config: Dict[str, str] = field(
        default_factory=lambda: {
            "year": "🗓️",
            "price": "💰",
            "reference": "#️⃣",
            "papers": "📄",
            "box": "📦",
            "condition": "⭐",
            "material": "🔩",
            "diameter": "📏",
            "search": "🔍",
            "check": "✅",
            "cross": "❌",
            "question": "❓",
        }
    )


# Site configurations
SITE_CONFIGS = {
    "worldoftime": SiteConfig(
        name="World of Time",
        key="worldoftime",
        url="https://www.worldoftime.de/Watches/NewArrivals",
        webhook_env_var="WORLDOFTIME_WEBHOOK_URL",
        color=0x2F4F4F,
        base_url="https://www.worldoftime.de",
        watch_container_selector="div.new-arrivals-watch, div.paged-clocks-container div.watch-link",
        link_selector="div.image a, div > a:has(img)",
        title_selector="div.text-truncate[style*='font-size: 17px'][style*='font-family: \\'AB\\'']",
        price_selector="span[style*='color: red']",
        image_selector="img",
        detail_page_selectors={
            "table": "div.watchDetailsRight table",
            "reference_header": "reference no",
            "year_header": "year",
            "condition_header": "condition",
            "material_header": "case material",
            "diameter_header": "diameter",
        },
        known_brands={
            "patek philippe": "Patek Philippe",
            "rolex vintage": "Rolex",
            "rolex": "Rolex",
            "omega": "Omega",
            "iwc": "IWC",
            "jaeger lecoultre": "Jaeger LeCoultre",
            "cartier": "Cartier",
            "breitling": "Breitling",
            "audemars piguet": "Audemars Piguet",
            "heuer": "Heuer",
            "universal geneve": "Universal Genève",
            "panerai": "Panerai",
            "tudor": "Tudor",
            "longines": "Longines",
            "zenith": "Zenith",
            "a. lange & söhne": "A. Lange & Söhne",
        },
    ),
    "grimmeissen": SiteConfig(
        name="Grimmeissen",
        key="grimmeissen",
        url="https://www.grimmeissen.de/de/uhren",
        webhook_env_var="GRIMMEISSEN_WEBHOOK_URL",
        color=0xDAA520,
        base_url="https://www.grimmeissen.de",
        watch_container_selector="li.product-item",
        link_selector="a.product-item-link",
        title_selector="a.product-item-link",
        price_selector="span.price-including-tax span.price",
        image_selector="img.product-image-photo",
        detail_page_selectors={
            "table": "table.shop-attributes-table",
            "specs_div": "div.product-info-details-content",
        },
        condition_mappings={
            "0": "★★★★★",
            "1": "★★★★☆",
            "2": "★★★☆☆",
            "3": "★★☆☆☆",
            "4": "★☆☆☆☆",
            "5": "☆☆☆☆☆",
        },
    ),
    "tropicalwatch": SiteConfig(
        name="Tropical Watch",
        key="tropicalwatch",
        url="https://tropicalwatch.com/",
        webhook_env_var="TROPICALWATCH_WEBHOOK_URL",
        color=0x008080,
        base_url="https://tropicalwatch.com",
        watch_container_selector="div.one_fourth",
        link_selector="a[href*='/watches/']",
        price_selector="span.price",
        image_selector="img",
        detail_page_selectors={"specs": "ul.watch-specs", "info": "div.info-value"},
    ),
    "juwelier_exchange": SiteConfig(
        name="Juwelier Exchange",
        key="juwelier_exchange",
        url="https://www.juwelier-exchange.de/uhren",
        webhook_env_var="JUWELIER_EXCHANGE_WEBHOOK_URL",
        color=0xB08D57,
        base_url="https://www.juwelier-exchange.de",
        watch_container_selector="ul.grid--view-items li.grid__item",
        link_selector="a.grid-view-item__link",
        title_selector="div.h4.grid-view-item__title",
        price_selector="span.product-price__price",
        image_selector="img.grid-view-item__image",
        detail_page_selectors={
            "product": "div.product-single",
            "content": "div.product-single__description",
        },
    ),
    "watch_out": SiteConfig(
        name="Watch Out",
        key="watch_out",
        url="https://www.watch-out.shop/collections/neu-eingetroffen?sort_by=created-descending",
        webhook_env_var="WATCH_OUT_WEBHOOK_URL",
        color=0xC0C0C0,
        base_url="https://www.watch-out.shop",
        watch_container_selector="div.grid-product__content",
        link_selector="a.grid-product__link",
        title_selector="div.grid-product__title",
        price_selector="span.grid-product__price",
        image_selector="div.grid__image-ratio img",
        detail_page_selectors={
            "info": "div.product-single__info-content",
            "description": "div.product-single__description",
        },
        known_brands={
            "a. lange & söhne": "A. Lange & Söhne",
            "audemars piguet": "Audemars Piguet",
            "breguet": "Breguet",
            "breitling": "Breitling",
            "cartier": "Cartier",
            "corum": "Corum",
            "etoile": "Etoile",
            "glashütte original": "Glashütte Original",
            "h.moser & cie.": "H.Moser & Cie.",
            "heuer": "Heuer",
            "iwc": "IWC",
            "jaeger lecoultre": "Jaeger LeCoultre",
            "omega": "Omega",
            "panerai": "Panerai",
            "parmigiani fleurier": "Parmigiani Fleurier",
            "patek philippe": "Patek Philippe",
            "piaget": "Piaget",
            "rolex": "Rolex",
            "tag heuer": "Tag Heuer",
            "tudor": "Tudor",
            "vacheron constantin": "Vacheron Constantin",
            "zenith": "Zenith",
        },
    ),
    "rueschenbeck": SiteConfig(
        name="Rüschenbeck",
        key="rueschenbeck",
        url="https://www.rueschenbeck.de/vintage-certified-pre-owned",
        webhook_env_var="RUESCHENBECK_WEBHOOK_URL",
        color=0xCFB53B,
        base_url="https://www.rueschenbeck.de",
        watch_container_selector="div.product-box",
        link_selector="a.product-link",
        title_selector="span.product-name",
        price_selector="span.product-price",
        image_selector="img.product-image",
        detail_page_selectors={
            "properties": "div.product-detail-properties",
            "tabs": "div.tab-content",
        },
    ),
}


# Initialize app configuration
APP_CONFIG = AppConfig()
