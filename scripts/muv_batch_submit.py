#!/usr/bin/env python3
"""Audit and optionally submit recent Discord watch notifications to MUV."""

import argparse
import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import unquote, urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")
load_dotenv()

import aiohttp  # noqa: E402

from action_store import ActionStore  # noqa: E402
from config import APP_CONFIG, SITE_CONFIGS  # noqa: E402
from logging_config import setup_logging  # noqa: E402
from models import WatchData  # noqa: E402
from muv_service import MUVActionService  # noqa: E402


def existing_unique_muv_url(record) -> Optional[str]:
    if not record:
        return None

    result = record.result or {}
    url = result.get("muv_sell_url")
    if not url and isinstance(result.get("submit_response"), dict):
        url = result["submit_response"].get("page_url")

    if url and MUVActionService._is_unique_muv_sell_url(url):
        return url
    return None


EXTRA_CHANNEL_ENVS = {
    "bachmann_scher": "BACHMANN_SCHER_CHANNEL_ID",
}

COMMON_BRANDS = {
    "A. Lange & Söhne",
    "Audemars Piguet",
    "Blancpain",
    "Breguet",
    "Breitling",
    "Cartier",
    "Chopard",
    "Chronoswiss",
    "Corum",
    "Czapek",
    "De Bethune",
    "Eberhard",
    "Etoile",
    "Girard Perregaux",
    "Glashütte Original",
    "H. Moser & Cie.",
    "Heuer",
    "Hublot",
    "IWC",
    "Jaeger LeCoultre",
    "Jaeger-LeCoultre",
    "Longines",
    "Omega",
    "Panerai",
    "Parmigiani Fleurier",
    "Patek Philippe",
    "Piaget",
    "Rolex",
    "TAG Heuer",
    "Tudor",
    "Universal Genève",
    "Urwerk",
    "Ulysse Nardin",
    "Vacheron Constantin",
    "Zenith",
}


@dataclass
class BatchItem:
    message_id: str
    timestamp: str
    channel_key: str
    action_id: str
    watch: WatchData


def configured_channels(overrides: Iterable[str]) -> Dict[str, str]:
    channels: Dict[str, str] = {}

    for key, site in SITE_CONFIGS.items():
        channel_id = site.discord_channel_id
        if channel_id:
            channels[key] = channel_id

    for key, env_name in EXTRA_CHANNEL_ENVS.items():
        channel_id = os.getenv(env_name)
        if channel_id:
            channels[key] = channel_id

    for override in overrides:
        if "=" not in override:
            raise ValueError(f"Invalid --channel value {override!r}; use name=id")
        key, channel_id = override.split("=", 1)
        key = key.strip()
        channel_id = channel_id.strip()
        if key and channel_id:
            channels[key] = channel_id

    return channels


async def fetch_discord_messages(
    session: aiohttp.ClientSession,
    channels: Dict[str, str],
    *,
    per_channel: int,
) -> List[Dict[str, Any]]:
    if not APP_CONFIG.discord_bot_token:
        raise RuntimeError("DISCORD_BOT_TOKEN is required to fetch Discord messages")

    headers = {
        "Authorization": f"Bot {APP_CONFIG.discord_bot_token}",
        "User-Agent": "DiscordBot (https://atlas.hopcomp.com, 1.0)",
    }
    api_base = APP_CONFIG.discord_api_base_url.rstrip("/")
    messages: List[Dict[str, Any]] = []

    for key, channel_id in channels.items():
        before = None
        remaining = per_channel
        while remaining > 0:
            limit = min(100, remaining)
            params = {"limit": str(limit)}
            if before:
                params["before"] = before

            url = f"{api_base}/channels/{channel_id}/messages"
            async with session.get(url, headers=headers, params=params) as response:
                if response.status != 200:
                    text = (await response.text())[:500]
                    raise RuntimeError(
                        f"Discord fetch failed for {key}/{channel_id}: "
                        f"{response.status} {text}"
                    )
                batch = await response.json()

            if not batch:
                break

            for message in batch:
                message["_channel_key"] = key
                message["_channel_id"] = channel_id
                messages.append(message)

            remaining -= len(batch)
            before = batch[-1].get("id")
            if len(batch) < limit:
                break

    return messages


def load_messages(path: Path) -> List[Dict[str, Any]]:
    data = json.loads(path.read_text())
    if isinstance(data, dict):
        data = data.get("messages") or data.get("rows") or data.get("data")
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a list of Discord messages")
    return data


def latest_items(messages: Iterable[Dict[str, Any]], limit: int) -> List[BatchItem]:
    items = [item for message in messages for item in items_from_message(message)]
    items.sort(key=lambda item: item.timestamp or "", reverse=True)

    selected: List[BatchItem] = []
    seen = set()
    for item in items:
        dedupe_key = item.action_id or item.watch.url
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        selected.append(item)
        if len(selected) >= limit:
            break
    return selected


def items_from_message(message: Dict[str, Any]) -> List[BatchItem]:
    items: List[BatchItem] = []
    for embed in message.get("embeds") or []:
        watch = watch_from_embed(message, embed)
        if not watch:
            continue

        action_id = extract_action_id(message) or ActionStore.action_id_for_watch(watch)
        items.append(
            BatchItem(
                message_id=str(message.get("id") or ""),
                timestamp=str(message.get("timestamp") or ""),
                channel_key=str(
                    message.get("_channel_key")
                    or message.get("channel_name")
                    or message.get("channel_id")
                    or ""
                ),
                action_id=action_id,
                watch=watch,
            )
        )
    return items


def watch_from_embed(
    message: Dict[str, Any], embed: Dict[str, Any]
) -> Optional[WatchData]:
    title = str(embed.get("title") or "").strip()
    url = str(embed.get("url") or "").strip()
    footer = _footer_text(embed)
    if not title or not url or " - Detected:" not in footer:
        return None

    site_name = footer.split(" - Detected:", 1)[0].strip() or "Discord"
    channel_key = str(message.get("_channel_key") or message.get("channel_name") or "")
    site_key = _site_key(site_name, channel_key)
    fields = _field_map(embed.get("fields") or [])
    left_title, title_reference = _split_title_reference(title)
    brand, model = _split_brand_model(left_title)

    price_display = fields.get("price")
    price, currency = _parse_price(price_display)
    detected_at = _parse_detected_at(footer) or _parse_message_time(
        message.get("timestamp")
    )
    reference = (
        fields.get("reference")
        or title_reference
        or MUVActionService._reference_from_url(url)
    )

    image_url = _embed_image_url(embed)
    return WatchData(
        title=title,
        url=url,
        site_name=site_name,
        site_key=site_key,
        brand=brand,
        model=model or left_title,
        reference=reference,
        year=fields.get("year"),
        price=price,
        currency=currency,
        price_display=price_display,
        image_url=image_url,
        image_urls=[image_url] if image_url else [],
        condition=fields.get("condition"),
        has_box=_parse_bool_field(fields.get("box")),
        has_papers=_parse_bool_field(fields.get("papers")),
        case_material=fields.get("case_material"),
        diameter=fields.get("diameter"),
        scraped_at=detected_at,
    )


def extract_action_id(message: Dict[str, Any]) -> Optional[str]:
    for component in _walk_components(message.get("components") or []):
        custom_id = component.get("custom_id")
        if not custom_id and component.get("url"):
            custom_id = _custom_id_from_url(component["url"])
        if not custom_id:
            continue

        action_id = ActionStore.parse_custom_id(
            custom_id, APP_CONFIG.action_token_secret
        )
        if action_id:
            return action_id
    return None


def save_batch_items(store: ActionStore, items: Iterable[BatchItem]) -> int:
    saved = 0
    for item in items:
        store.save_listing(
            item.action_id,
            ActionStore._watch_to_dict(item.watch),
        )
        saved += 1
    return saved


async def audit_items(
    service: MUVActionService,
    items: Iterable[BatchItem],
    *,
    check_downloads: bool,
    concurrency: int = 8,
    per_host_concurrency: int = 2,
) -> List[Dict[str, Any]]:
    await service._load_whitelist()
    semaphore = asyncio.Semaphore(max(1, concurrency))
    host_semaphores: Dict[str, asyncio.Semaphore] = {}

    def host_semaphore(item: BatchItem) -> asyncio.Semaphore:
        host = urlparse(item.watch.url).netloc.casefold()
        if host not in host_semaphores:
            host_semaphores[host] = asyncio.Semaphore(
                _host_concurrency(host, per_host_concurrency)
            )
        return host_semaphores[host]

    async def audit_one(index: int, item: BatchItem) -> Dict[str, Any]:
        async with host_semaphore(item):
            async with semaphore:
                return await _audit_item(service, index, item, check_downloads)

    return await asyncio.gather(
        *(audit_one(index, item) for index, item in enumerate(items, start=1))
    )


async def _audit_item(
    service: MUVActionService,
    index: int,
    item: BatchItem,
    check_downloads: bool,
) -> Dict[str, Any]:
    listing = await service._listing_with_submission_images(
        ActionStore._watch_to_dict(item.watch)
    )
    match = await service.match_listing(listing)
    image_urls = listing.get("image_urls") or []
    errors = []
    if not match:
        errors.append("No MUV model match above threshold")
    if len(image_urls) < APP_CONFIG.muv_min_picture_count:
        errors.append(
            f"At least {APP_CONFIG.muv_min_picture_count} image URLs are required"
        )

    downloaded = None
    if check_downloads and len(image_urls) >= APP_CONFIG.muv_min_picture_count:
        paths = await service._download_images(image_urls)
        downloaded = len(paths)
        for path in paths:
            try:
                os.unlink(path)
            except OSError:
                pass
        if downloaded < APP_CONFIG.muv_min_picture_count:
            errors.append(
                f"Downloaded only {downloaded} usable images; "
                f"{APP_CONFIG.muv_min_picture_count} required"
            )

    return {
        "idx": index,
        "timestamp": item.timestamp,
        "channel": item.channel_key,
        "message_id": item.message_id,
        "action_id": item.action_id,
        "site": item.watch.site_name,
        "title": item.watch.title,
        "url": item.watch.url,
        "match": f"{match.brand_name} {match.model_name}" if match else None,
        "confidence": match.confidence if match else None,
        "image_urls": len(image_urls),
        "downloadable_images": downloaded,
        "ready": not errors,
        "errors": errors,
    }


def submission_config_errors(requester_id: Optional[str] = None) -> List[str]:
    errors = []
    seller_record = None
    if requester_id:
        seller_record = type("SellerRecord", (), {"requested_by": requester_id})()
    seller = MUVActionService._seller_for_record(seller_record)

    if APP_CONFIG.muv_submission_mode != "browser":
        errors.append("MUV_SUBMISSION_MODE must be browser")
    if not APP_CONFIG.muv_auto_submit:
        errors.append("MUV_AUTO_SUBMIT must be true")
    requester_error = MUVActionService._requester_permission_error(seller_record)
    if requester_error:
        errors.append(requester_error)
    if not seller.get("email"):
        errors.append("MUV_SELLER_EMAIL is missing")
    if not seller.get("firstName"):
        errors.append("MUV_SELLER_FIRST_NAME is missing")
    if not seller.get("lastName"):
        errors.append("MUV_SELLER_LAST_NAME is missing")
    if not APP_CONFIG.muv_accept_terms:
        errors.append("MUV_ACCEPT_TERMS must be true")
    if not APP_CONFIG.muv_confirm_eu_seller:
        errors.append("MUV_CONFIRM_EU_SELLER must be true")
    return errors


async def submit_ready_items(
    store: ActionStore,
    service: MUVActionService,
    rows: List[Dict[str, Any]],
    *,
    requester_id: Optional[str],
    requester_name: str,
    max_submit: Optional[int],
) -> Dict[str, Any]:
    config_errors = submission_config_errors(requester_id)
    if config_errors:
        raise RuntimeError("; ".join(config_errors))

    submitted = []
    skipped = []
    seen_urls = set()
    ready_rows = [row for row in rows if row["ready"]]
    if max_submit is not None:
        ready_rows = ready_rows[:max_submit]

    for row in ready_rows:
        record = store.get(row["action_id"])
        existing_muv_url = existing_unique_muv_url(record)
        if existing_muv_url:
            store.save_offer_link(existing_muv_url, row["action_id"])

        if record and record.status in {"submitted", "completed"}:
            skipped.append(
                {
                    **row,
                    "skip_reason": f"already {record.status}",
                    "muv_sell_url": existing_muv_url,
                }
            )
            continue

        if existing_muv_url:
            skipped.append(
                {
                    **row,
                    "skip_reason": "already has MUV Sell link",
                    "muv_sell_url": existing_muv_url,
                }
            )
            continue

        store.queue_action(
            row["action_id"],
            requested_by=requester_id,
            requested_by_name=requester_name,
            interaction_id=f"batch:{row['message_id']}",
        )
        result = await service.handle_action(row["action_id"])
        muv_url = result.data.get("muv_sell_url")
        ok = bool(
            result.submitted
            and muv_url
            and MUVActionService._is_unique_muv_sell_url(muv_url)
            and muv_url not in seen_urls
        )
        if muv_url:
            seen_urls.add(muv_url)
        submitted.append(
            {
                **row,
                "submitted": ok,
                "muv_sell_url": muv_url,
                "status": result.status,
                "error": result.error,
            }
        )

    return {
        "attempted": len(submitted),
        "submitted": sum(1 for row in submitted if row["submitted"]),
        "skipped": skipped,
        "rows": submitted,
    }


async def run(args: argparse.Namespace) -> int:
    if args.submit_ready:
        config_errors = submission_config_errors(args.requester_id)
        if config_errors:
            raise RuntimeError("; ".join(config_errors))

    logger = setup_logging(args.log_level)
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        if args.messages_json:
            messages = load_messages(Path(args.messages_json))
        else:
            channels = configured_channels(args.channel)
            if not channels:
                raise RuntimeError("No Discord site channels are configured")
            messages = await fetch_discord_messages(
                session, channels, per_channel=args.per_channel
            )

        items = latest_items(messages, args.limit)
        store = ActionStore(args.action_store or APP_CONFIG.action_store_file)
        try:
            save_batch_items(store, items)
            service = MUVActionService(session, store, logger)
            rows = await audit_items(
                service,
                items,
                check_downloads=args.check_downloads,
                concurrency=args.audit_concurrency,
                per_host_concurrency=args.per_host_concurrency,
            )
            result = {
                "summary": {
                    "audited": len(rows),
                    "ready": sum(1 for row in rows if row["ready"]),
                    "failed": sum(1 for row in rows if not row["ready"]),
                },
                "submission_config_errors": submission_config_errors(args.requester_id),
                "rows": rows,
            }

            if args.submit_ready:
                result["submission"] = await submit_ready_items(
                    store,
                    service,
                    rows,
                    requester_id=args.requester_id,
                    requester_name=args.requester_name,
                    max_submit=args.max_submit,
                )
                required = args.require_submitted
                if (
                    required is not None
                    and result["submission"]["submitted"] != required
                ):
                    result["summary"]["error"] = (
                        f"Submitted {result['submission']['submitted']} "
                        f"unique MUV links; required {required}"
                    )
                    exit_code = 2
                else:
                    exit_code = 0
            else:
                exit_code = 0

            output = json.dumps(result, indent=2, ensure_ascii=False)
            if args.audit_output:
                Path(args.audit_output).write_text(output)
            print(output)
            return exit_code
        finally:
            store.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch recent Discord listing notifications, map them to MUV, "
            "and optionally submit ready listings from the VM."
        )
    )
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--per-channel", type=int, default=100)
    parser.add_argument("--messages-json")
    parser.add_argument("--audit-output")
    parser.add_argument("--action-store")
    parser.add_argument("--channel", action="append", default=[], help="name=id")
    parser.add_argument("--check-downloads", action="store_true")
    parser.add_argument("--audit-concurrency", type=int, default=8)
    parser.add_argument("--per-host-concurrency", type=int, default=2)
    parser.add_argument("--submit-ready", action="store_true")
    parser.add_argument("--max-submit", type=int)
    parser.add_argument("--require-submitted", type=int)
    parser.add_argument("--requester-id")
    parser.add_argument("--requester-name", default="batch")
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
    )
    return parser


def _walk_components(components: Iterable[Dict[str, Any]]):
    for component in components:
        yield component
        yield from _walk_components(component.get("components") or [])


def _custom_id_from_url(url: str) -> Optional[str]:
    path = urlparse(url).path.rstrip("/")
    if not path:
        return None
    custom_id = unquote(path.rsplit("/", 1)[-1])
    return custom_id if custom_id.startswith("muv:") else None


def _host_concurrency(host: str, default: int) -> int:
    if "worldoftime.de" in host:
        return 1
    return max(1, default)


def _footer_text(embed: Dict[str, Any]) -> str:
    footer = embed.get("footer") or ""
    if isinstance(footer, dict):
        return str(footer.get("text") or "")
    return str(footer)


def _embed_image_url(embed: Dict[str, Any]) -> Optional[str]:
    image = embed.get("image") or embed.get("thumbnail") or {}
    if isinstance(image, dict):
        return image.get("url")
    return str(image) if image else None


def _field_map(fields: Iterable[Dict[str, Any]]) -> Dict[str, str]:
    mapped: Dict[str, str] = {}
    key_map = {
        "price": "price",
        "reference": "reference",
        "year": "year",
        "condition": "condition",
        "box": "box",
        "papers": "papers",
        "casematerial": "case_material",
        "diameter": "diameter",
    }
    for field in fields:
        name = re.sub(r"[^A-Za-z]", "", str(field.get("name") or "")).casefold()
        key = key_map.get(name)
        value = _clean_field_value(field.get("value"))
        if key and value:
            mapped[key] = value
    return mapped


def _clean_field_value(value: Any) -> Optional[str]:
    text = re.sub(r"\*\*", "", str(value or "")).strip()
    return text if text and text != "\u200b" else None


def _site_key(site_name: str, channel_key: str) -> str:
    if channel_key:
        return channel_key
    normalized = re.sub(r"[^a-z0-9]+", "_", site_name.casefold()).strip("_")
    if normalized == "world_of_time":
        return "worldoftime"
    if normalized == "tropical_watch":
        return "tropicalwatch"
    return normalized


def _split_title_reference(title: str) -> Tuple[str, Optional[str]]:
    if " | " not in title:
        return title.strip(), None
    left, reference = title.rsplit(" | ", 1)
    return left.strip(), reference.strip() or None


def _split_brand_model(title: str) -> Tuple[Optional[str], Optional[str]]:
    brands = sorted(_known_brands(), key=len, reverse=True)
    normalized_title = _normalize_text(title)
    for brand in brands:
        normalized_brand = _normalize_text(brand)
        if normalized_title == normalized_brand:
            return brand, None
        if normalized_title.startswith(normalized_brand + " "):
            return brand, title[len(brand) :].strip(" -")
    return None, title.strip() or None


def _known_brands() -> set:
    brands = set(COMMON_BRANDS)
    for site in SITE_CONFIGS.values():
        brands.update(site.known_brands.values())
    return brands


def _normalize_text(value: str) -> str:
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value.casefold())
    return re.sub(r"\s+", " ", value).strip()


def _parse_price(value: Optional[str]) -> Tuple[Optional[Decimal], str]:
    if not value:
        return None, "EUR"
    currency = "EUR" if "€" in value or "eur" in value.casefold() else "USD"
    match = re.search(r"\d[\d.,]*", value)
    if not match:
        return None, currency
    text = match.group(0)
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        whole, _, fraction = text.rpartition(",")
        text = (
            whole.replace(".", "") + "." + fraction
            if len(fraction) <= 2
            else text.replace(",", "")
        )
    else:
        text = text.replace(".", "")
    try:
        return Decimal(text), currency
    except InvalidOperation:
        return None, currency


def _parse_bool_field(value: Optional[str]) -> Optional[bool]:
    if not value:
        return None
    lowered = value.casefold()
    if "✅" in value or lowered in {"yes", "true", "with", "box", "papers"}:
        return True
    if "❌" in value or lowered in {"no", "false", "without"}:
        return False
    return None


def _parse_detected_at(footer: str) -> datetime:
    match = re.search(r"Detected:\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", footer)
    if not match:
        return datetime.now()
    try:
        return datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return datetime.now()


def _parse_message_time(value: Any) -> datetime:
    if not value:
        return datetime.now()
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(
            tzinfo=None
        )
    except ValueError:
        return datetime.now()


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
