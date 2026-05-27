"""MUV matching and Discord result notification service."""

import base64
import hashlib
import json
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from html import unescape
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import aiohttp

from action_store import ActionRecord, ActionStore
from config import APP_CONFIG
from models import WatchData
from utils import fetch_page


@dataclass
class MUVMatch:
    brand_name: str
    brand_id: int
    model_name: str
    model_id: int
    ref_mp: int
    confidence: float


@dataclass
class MUVResult:
    status: str
    title: str
    description: str
    data: Dict[str, Any]
    error: Optional[str] = None
    submitted: bool = False


class MUVActionService:
    """Process stored listings for MUV and publish result webhooks."""

    def __init__(self, session: aiohttp.ClientSession, store: ActionStore, logger):
        self.session = session
        self.store = store
        self.logger = logger
        self._whitelist: Optional[List[Dict[str, Any]]] = None

    async def handle_action(self, action_id: str) -> MUVResult:
        record = self.store.get(action_id)
        if not record:
            result = MUVResult(
                status="failed",
                title="MUV action failed",
                description="The listing action was not found in the local action store.",
                data={"action_id": action_id},
                error="Unknown action id",
            )
            await self._send_result_webhook(None, result)
            return result

        self.store.update_status(action_id, "running")

        try:
            result = await self._prepare_or_submit(record)
        except Exception as exc:
            self.logger.exception("Unexpected MUV action failure for %s", action_id)
            result = MUVResult(
                status="failed",
                title="MUV action failed",
                description="Unexpected error while preparing the MUV request.",
                data={"action_id": action_id},
                error=str(exc),
            )

        self.store.update_status(
            action_id,
            result.status,
            result=result.data,
            last_error=result.error,
            submitted=result.submitted,
        )
        await self._send_result_webhook(record, result)
        return result

    async def publish_offer(
        self, action_id: str, offer_payload: Dict[str, Any]
    ) -> MUVResult:
        """Publish a received MUV offer for a previously stored listing."""
        record = self.store.get(action_id)
        if not record:
            result = MUVResult(
                status="failed",
                title="MUV offer could not be matched",
                description="A MUV offer webhook arrived for an unknown local action id.",
                data={"action_id": action_id, "muv_offer": offer_payload},
                error="Unknown action id",
            )
            await self._send_result_webhook(None, result)
            return result

        result_data = dict(record.result or {})
        result_data["listing"] = result_data.get("listing") or self._listing_summary(
            record.listing
        )
        result_data["muv_offer"] = offer_payload
        if offer_payload.get("muv_url"):
            result_data["muv_sell_url"] = offer_payload["muv_url"]

        result = MUVResult(
            status="completed",
            title="MUV offer received",
            description="MUV offer data was received on the VM and linked to the original listing.",
            data=result_data,
            submitted=bool(record.submitted_at),
        )
        self.store.update_status(action_id, "completed", result=result_data)
        await self._send_result_webhook(record, result)
        return result

    async def publish_offer_link(self, url: str) -> MUVResult:
        """Fetch a MUV offer page and publish its current state to Discord."""
        offer_payload = await self.fetch_offer_link(url)
        if not offer_payload:
            result = MUVResult(
                status="failed",
                title="MUV offer link could not be read",
                description="The MUV offer page did not expose a readable offer state.",
                data={"muv_offer": {"muv_url": url}},
                error="Could not parse MUV offer page",
            )
            await self._send_result_webhook(None, result)
            return result

        result = self._result_for_offer_payload(offer_payload)
        await self._send_result_webhook(None, result)
        return result

    async def register_configured_offer_links(self):
        """Persist offer links configured through the environment."""
        if not self.store:
            return

        for url in self._configured_offer_links():
            self.store.save_offer_link(url)

    async def monitor_offer_links(self) -> int:
        """Poll tracked MUV offer links and notify only when state changes."""
        if not self.store:
            return 0

        sent = 0
        for link in self.store.list_offer_links():
            offer_payload = await self.fetch_offer_link(link.url)
            if not offer_payload:
                continue

            fingerprint = self._offer_fingerprint(offer_payload)
            if fingerprint == link.last_fingerprint:
                continue

            if link.action_id:
                result = await self.publish_offer(link.action_id, offer_payload)
            else:
                result = self._result_for_offer_payload(offer_payload)
                await self._send_result_webhook(None, result)

            self.store.update_offer_link_state(
                link.url,
                fingerprint,
                offer_payload,
                notified=result.status != "failed",
            )
            sent += 1

        return sent

    async def fetch_offer_link(self, url: str) -> Optional[Dict[str, Any]]:
        html = await fetch_page(self.session, url, self.logger)
        if not html:
            return None
        return self.parse_offer_page(html, url)

    async def _prepare_or_submit(self, record: ActionRecord) -> MUVResult:
        listing = record.listing
        match = await self.match_listing(listing)
        if not match:
            return MUVResult(
                status="failed",
                title="MUV mapping failed",
                description="Could not confidently map this listing to a MUV brand/model.",
                data={"listing": self._listing_summary(listing)},
                error="No MUV model match above threshold",
            )

        request_payload = self._build_request_payload(listing, match)
        validation_errors = self._validate_for_submit(listing)

        data = {
            "listing": self._listing_summary(listing),
            "muv": self._match_to_dict(match),
            "request_payload": request_payload,
            "auto_submit": APP_CONFIG.muv_auto_submit,
            "validation_errors": validation_errors,
            "muv_sell_url": f"{APP_CONFIG.muv_base_url.rstrip('/')}/sell",
        }

        if validation_errors:
            status = "prepared" if not APP_CONFIG.muv_auto_submit else "failed"
            return MUVResult(
                status=status,
                title=(
                    "MUV request prepared"
                    if status == "prepared"
                    else "MUV submit blocked"
                ),
                description=(
                    "The listing was mapped to MUV, but automatic submission is not enabled "
                    "or required submit data is missing."
                ),
                data=data,
                error=(
                    "; ".join(validation_errors) if APP_CONFIG.muv_auto_submit else None
                ),
            )

        submit_result = await self._submit_payload(request_payload)
        data["submit_response"] = submit_result
        if submit_result.get("page_url"):
            data["muv_sell_url"] = submit_result["page_url"]

        if not submit_result.get("ok"):
            return MUVResult(
                status="failed",
                title="MUV submit failed",
                description="The VM attempted the MUV API flow but MUV rejected or blocked it.",
                data=data,
                error=submit_result.get("error", "Unknown MUV submission error"),
            )

        if self.store and submit_result.get("page_url"):
            self.store.save_offer_link(submit_result["page_url"], record.action_id)

        return MUVResult(
            status="submitted",
            title="MUV request submitted",
            description="The listing was submitted to MUV from the VM.",
            data=data,
            submitted=True,
        )

    async def match_listing(self, listing: Dict[str, Any]) -> Optional[MUVMatch]:
        whitelist = await self._load_whitelist()
        if not whitelist:
            return None

        brand = self._normalize_brand(listing.get("brand") or "")
        model = self._normalize(listing.get("model") or "")
        title = self._normalize(listing.get("title") or "")
        search_text = " ".join(part for part in [brand, model, title] if part)

        best: Optional[Tuple[float, int, Dict[str, Any]]] = None
        for item in whitelist:
            item_brand = self._normalize_brand(item.get("BrandName") or "")
            item_model = self._normalize(item.get("ModelName") or "")
            item_full = f"{item_brand} {item_model}".strip()
            if brand and item_brand != brand:
                continue

            score = SequenceMatcher(None, search_text, item_full).ratio()
            if item_model and item_model in title:
                score = max(score, min(0.99, 0.90 + len(item_model) / 100))
            if item_full and item_full in search_text:
                score = max(score, min(0.995, 0.94 + len(item_full) / 200))
            if model and item_model and item_model == model:
                score = max(score, 1.0)

            specificity = len(item_model)
            if (
                not best
                or score > best[0]
                or (score == best[0] and specificity > best[1])
            ):
                best = (score, specificity, item)

        if not best or best[0] < APP_CONFIG.muv_match_threshold:
            return None

        item = best[2]
        return MUVMatch(
            brand_name=item["BrandName"],
            brand_id=int(item["BrandId"]),
            model_name=item["ModelName"],
            model_id=int(item["ModelId"]),
            ref_mp=int(item.get("RefMP") or 0),
            confidence=round(best[0], 3),
        )

    async def _load_whitelist(self) -> List[Dict[str, Any]]:
        if self._whitelist is not None:
            return self._whitelist

        url = APP_CONFIG.muv_base_url.rstrip("/") + "/"
        content = await fetch_page(self.session, url, self.logger)
        if not content:
            self._whitelist = []
            return self._whitelist

        match = re.search(r"whitelistPayload\s*=\s*'([^']+)'", content)
        if not match:
            self.logger.error("Could not find MUV model whitelist payload")
            self._whitelist = []
            return self._whitelist

        try:
            from urllib.parse import unquote

            decoded = base64.b64decode(match.group(1)).decode("utf-8")
            self._whitelist = json.loads(unquote(decoded))
        except Exception as exc:
            self.logger.error("Could not decode MUV model whitelist: %s", exc)
            self._whitelist = []

        return self._whitelist

    def _build_request_payload(
        self, listing: Dict[str, Any], match: MUVMatch
    ) -> Dict[str, Any]:
        condition = self._map_condition(listing.get("condition"))
        scope = self._map_scope(listing.get("has_box"), listing.get("has_papers"))
        return {
            "modelId": match.model_id,
            "brandId": match.brand_id,
            "refMp": match.ref_mp,
            "brandName": match.brand_name,
            "modelName": match.model_name,
            "referenceNumber": listing.get("reference"),
            "yearOfProduction": self._int_or_none(listing.get("year")),
            "condition": condition,
            "scopeOfDelivery": scope,
            "caseMaterial": listing.get("case_material"),
            "seller": {
                "email": APP_CONFIG.muv_seller_email or None,
                "firstName": APP_CONFIG.muv_seller_first_name or None,
                "lastName": APP_CONFIG.muv_seller_last_name or None,
            },
            "comment": self._build_comment(listing),
            "imageUrls": listing.get("image_urls")
            or ([listing["image_url"]] if listing.get("image_url") else []),
            "sourceUrl": listing.get("url"),
        }

    def _validate_for_submit(self, listing: Dict[str, Any]) -> List[str]:
        errors = []
        if not APP_CONFIG.muv_auto_submit:
            errors.append("MUV_AUTO_SUBMIT is false")
        if not APP_CONFIG.muv_seller_email:
            errors.append("MUV_SELLER_EMAIL is missing")
        if not APP_CONFIG.muv_seller_first_name:
            errors.append("MUV_SELLER_FIRST_NAME is missing")
        if not APP_CONFIG.muv_seller_last_name:
            errors.append("MUV_SELLER_LAST_NAME is missing")
        if not APP_CONFIG.muv_accept_terms:
            errors.append("MUV_ACCEPT_TERMS must be true")
        if not APP_CONFIG.muv_confirm_eu_seller:
            errors.append("MUV_CONFIRM_EU_SELLER must be true")

        images = listing.get("image_urls") or (
            [listing["image_url"]] if listing.get("image_url") else []
        )
        if len([url for url in images if url]) < APP_CONFIG.muv_min_picture_count:
            errors.append(
                f"At least {APP_CONFIG.muv_min_picture_count} image URLs are required"
            )
        return errors

    async def _submit_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if APP_CONFIG.muv_submission_mode == "browser":
            return await self._submit_with_browser(payload)

        return {
            "ok": False,
            "error": (
                "MUV_SUBMISSION_MODE is set to prepare. Set MUV_SUBMISSION_MODE=browser "
                "on the VM after installing Playwright Chromium to submit the prepared payload."
            ),
            "payload": payload,
        }

    async def _submit_with_browser(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        image_paths: List[str] = []
        try:
            try:
                from playwright.async_api import async_playwright
            except ImportError:
                return {
                    "ok": False,
                    "error": "playwright is not installed. Install requirements and run: python -m playwright install chromium",
                }

            image_paths = await self._download_images(payload.get("imageUrls") or [])
            if len(image_paths) < APP_CONFIG.muv_min_picture_count:
                return {
                    "ok": False,
                    "error": f"Downloaded only {len(image_paths)} usable images; {APP_CONFIG.muv_min_picture_count} required",
                }

            base_url = APP_CONFIG.muv_base_url.rstrip("/")
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(
                    headless=True, args=["--no-sandbox"]
                )
                page = await browser.new_page()
                try:
                    await page.goto(
                        base_url + "/", wait_until="networkidle", timeout=60000
                    )
                    await page.evaluate(
                        "(item) => localStorage.setItem('searchResultModel', JSON.stringify(item))",
                        {
                            "BrandName": payload["brandName"],
                            "BrandId": payload.get("brandId"),
                            "ModelName": payload["modelName"],
                            "ModelId": payload["modelId"],
                            "RefMP": payload.get("refMp", 0),
                        },
                    )
                    await page.goto(
                        base_url + "/sell", wait_until="networkidle", timeout=60000
                    )

                    await page.get_by_role("combobox").nth(2).select_option(
                        index=max(payload["condition"] - 1, 0)
                    )
                    await page.get_by_role("combobox").nth(3).select_option(
                        index=max(payload["scopeOfDelivery"] - 1, 0)
                    )

                    if payload.get("referenceNumber"):
                        await page.get_by_placeholder(
                            re.compile("Reference Number", re.I)
                        ).fill(str(payload["referenceNumber"]))
                    if payload.get("yearOfProduction"):
                        await page.get_by_role("spinbutton").fill(
                            str(payload["yearOfProduction"])
                        )
                    if payload.get("comment"):
                        await page.get_by_placeholder(re.compile("Comment", re.I)).fill(
                            payload["comment"]
                        )

                    seller = payload["seller"]
                    await page.get_by_placeholder(
                        re.compile("Email Address", re.I)
                    ).fill(seller["email"])
                    await page.get_by_placeholder(re.compile("First Name", re.I)).fill(
                        seller["firstName"]
                    )
                    await page.get_by_placeholder(re.compile("Last Name", re.I)).fill(
                        seller["lastName"]
                    )

                    await page.locator('input[type="file"]').first.set_input_files(
                        image_paths
                    )
                    await page.get_by_label(
                        re.compile("Privacy Policy|General Purchase Terms", re.I)
                    ).check()
                    await page.get_by_label(re.compile("European Union", re.I)).check()
                    await page.get_by_role(
                        "button", name=re.compile("Submit Request", re.I)
                    ).click()
                    await page.wait_for_timeout(5000)

                    body_text = await page.locator("body").inner_text(timeout=10000)
                    if "Please review your information" in body_text:
                        return {
                            "ok": False,
                            "error": body_text[-1500:],
                            "page_url": page.url,
                        }
                    return {
                        "ok": True,
                        "page_url": page.url,
                        "body_excerpt": body_text[-1500:],
                    }
                finally:
                    await browser.close()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        finally:
            for path in image_paths:
                try:
                    os.unlink(path)
                except OSError:
                    pass

    async def _download_images(self, image_urls: List[str]) -> List[str]:
        paths = []
        for image_url in [url for url in image_urls if url][:12]:
            parsed = urlparse(image_url)
            suffix = Path(parsed.path).suffix or ".jpg"
            fd, path = tempfile.mkstemp(prefix="muv-image-", suffix=suffix)
            os.close(fd)
            try:
                timeout = aiohttp.ClientTimeout(total=30)
                async with self.session.get(image_url, timeout=timeout) as response:
                    if response.status != 200:
                        os.unlink(path)
                        continue
                    with open(path, "wb") as f:
                        f.write(await response.read())
                paths.append(path)
            except Exception:
                try:
                    os.unlink(path)
                except OSError:
                    pass
        return paths

    async def _send_result_webhook(
        self, record: Optional[ActionRecord], result: MUVResult
    ):
        webhook_url = APP_CONFIG.muv_result_webhook_url
        if not webhook_url:
            self.logger.info(
                "No MUV_RESULT_WEBHOOK_URL configured; result not posted to Discord"
            )
            return

        embed = self._build_result_embed(record, result)
        payload = {"embeds": [embed]}
        timeout = aiohttp.ClientTimeout(total=15)

        try:
            async with self.session.post(
                webhook_url, json=payload, timeout=timeout
            ) as response:
                if response.status not in (200, 204):
                    text = (await response.text())[:500]
                    self.logger.error(
                        "MUV result webhook failed: %s %s", response.status, text
                    )
        except Exception as exc:
            self.logger.error("Error sending MUV result webhook: %s", exc)

    def _build_result_embed(
        self, record: Optional[ActionRecord], result: MUVResult
    ) -> Dict[str, Any]:
        listing = (
            record.listing
            if record
            else result.data.get("listing")
            or self._listing_from_offer(result.data.get("muv_offer") or {})
        )
        color = {
            "submitted": 0x2ECC71,
            "prepared": 0xF1C40F,
            "failed": 0xE74C3C,
            "completed": 0x2ECC71,
        }.get(result.status, 0x95A5A6)

        watch = self._watch_from_listing(listing)
        embed = watch.to_discord_embed(color)
        watch_title = embed.get("title") or listing.get("title") or "Unknown Watch"
        embed["title"] = f"{result.title}: {watch_title}"[:256]
        embed["description"] = result.description
        if not embed.get("url"):
            embed.pop("url", None)

        muv_fields = [
            {
                "name": "MUV Status:",
                "value": f"**{result.status}**",
                "inline": True,
            },
        ]

        offer = result.data.get("muv_offer")
        if offer:
            offer_price = self._offer_price_display(offer)
            if offer_price:
                muv_fields.append(
                    {
                        "name": f"{APP_CONFIG.emoji_config['price']} MUV Offer:",
                        "value": f"**{offer_price}**",
                        "inline": True,
                    }
                )
            offer_text = self._format_offer(offer)
            if offer_text:
                muv_fields.append(
                    {
                        "name": "MUV Offer Details:",
                        "value": offer_text[:1000],
                        "inline": False,
                    }
                )

        muv = result.data.get("muv")
        if muv:
            muv_fields.append(
                {
                    "name": "MUV Match:",
                    "value": f"**{muv['brand_name']} {muv['model_name']}** ({muv['confidence']})",
                    "inline": False,
                }
            )

        if result.data.get("muv_sell_url"):
            muv_fields.append(
                {
                    "name": "MUV Link:",
                    "value": f"[**Open MUV flow**]({result.data['muv_sell_url']})",
                    "inline": False,
                }
            )

        validation_errors = result.data.get("validation_errors") or []
        if validation_errors:
            muv_fields.append(
                {
                    "name": "Submit Requirements:",
                    "value": "\n".join(f"- {item}" for item in validation_errors)[
                        :1000
                    ],
                    "inline": False,
                }
            )

        if result.error:
            muv_fields.append(
                {"name": "Error:", "value": result.error[:1000], "inline": False}
            )

        fields = embed.get("fields", [])
        insert_at = 1 if fields else 0
        embed["fields"] = fields[:insert_at] + muv_fields + fields[insert_at:]
        footer_bits = ["MUV"]
        if record:
            footer_bits.append(f"Action {record.action_id[:12]}")
        footer_bits.append(f"Updated: {watch.scraped_at.strftime('%Y-%m-%d %H:%M:%S')}")
        embed["footer"] = {"text": " - ".join(footer_bits)}
        return embed

    @classmethod
    def parse_offer_page(cls, html: str, url: str) -> Optional[Dict[str, Any]]:
        """Extract accepted/rejected offer state from MUV prerendered HTML."""
        match = re.search(r'"parameterValues"\s*:\s*"([^"]+)"', html)
        if not match:
            return None

        try:
            decoded = base64.b64decode(unescape(match.group(1))).decode("utf-8")
            values = json.loads(decoded)
        except Exception:
            return None

        if not isinstance(values, list) or len(values) < 2:
            return None

        view_model = values[1] or {}
        offer_request = view_model.get("offerRequest") or {}
        review = offer_request.get("reviewStep") or {}
        watches = [
            cls._parse_offer_watch(item) for item in (review.get("watches") or [])
        ]
        watches = [watch for watch in watches if watch]
        price = next(
            (watch["price"] for watch in watches if watch.get("price") is not None),
            None,
        )

        reviewed = bool(review.get("isReviewed"))
        if offer_request.get("isCanceled"):
            status = "canceled"
        elif not reviewed:
            status = "pending"
        elif any(watch.get("status") == "offered" for watch in watches):
            status = "offered"
        elif watches:
            status = "rejected"
        else:
            status = "reviewed"

        payload = {
            "source": "muv_offer_link",
            "status": status,
            "muv_url": url,
            "request_id": offer_request.get("requestId"),
            "short_reference": offer_request.get("shortReference"),
            "created_utc": offer_request.get("createdUTC"),
            "reviewed": reviewed,
            "is_offer_expired": bool(review.get("isOfferExpired")),
            "offer_expiry_date_utc": review.get("offerExpiryDateUTC"),
            "currency": "EUR",
            "watches": watches,
        }
        if price is not None:
            payload["price"] = cls._format_money(price)
        payload["message"] = cls._offer_message(payload)
        return payload

    @classmethod
    def _parse_offer_watch(cls, item: Dict[str, Any]) -> Dict[str, Any]:
        details = item.get("watchDetails") or {}
        price = item.get("offeredPurchasePrice")
        status = (
            "offered"
            if price is not None
            or item.get("isDirectPurchasePossible")
            or item.get("isCommissionDealPossible")
            else "rejected"
        )
        return {
            "status": status,
            "brand": details.get("brand"),
            "model": details.get("model"),
            "reference": details.get("referenceNumber"),
            "condition": details.get("conditionStringValue"),
            "scope": details.get("scopeOfDeliveryStringValue"),
            "price": price,
            "price_display": cls._format_money(price) if price is not None else None,
            "picture_url": details.get("pictureUrl"),
            "offered_watch_id": details.get("offeredWatchId"),
            "is_negotiated": bool(item.get("isNegotiated")),
            "is_ready_to_proceed": bool(item.get("isReadyToProceed")),
        }

    @staticmethod
    def _offer_fingerprint(offer: Dict[str, Any]) -> str:
        relevant = {
            "status": offer.get("status"),
            "price": offer.get("price"),
            "currency": offer.get("currency"),
            "reviewed": offer.get("reviewed"),
            "is_offer_expired": offer.get("is_offer_expired"),
            "watches": offer.get("watches"),
        }
        encoded = json.dumps(relevant, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _configured_offer_links() -> List[str]:
        raw = APP_CONFIG.muv_offer_link_urls or ""
        return [item.strip() for item in raw.split(",") if item.strip()]

    def _result_for_offer_payload(self, offer_payload: Dict[str, Any]) -> MUVResult:
        status = offer_payload.get("status") or "reviewed"
        title = {
            "offered": "MUV offer received",
            "rejected": "MUV offer rejected",
            "pending": "MUV offer still pending",
            "canceled": "MUV request canceled",
        }.get(status, "MUV offer link reviewed")
        description = offer_payload.get("message") or "MUV offer link state changed."
        result_status = "completed" if status in {"offered", "rejected"} else "prepared"
        return MUVResult(
            status=result_status,
            title=title,
            description=description,
            data={
                "muv_offer": offer_payload,
                "muv_sell_url": offer_payload.get("muv_url"),
            },
        )

    @staticmethod
    def _normalize(value: str) -> str:
        value = (
            unicodedata.normalize("NFKD", value.casefold())
            .encode("ascii", "ignore")
            .decode("ascii")
        )
        return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()

    @classmethod
    def _normalize_brand(cls, value: str) -> str:
        normalized = cls._normalize(value)
        aliases = {
            "bulgari": "bvlgari",
            "bvlgari": "bvlgari",
            "glashuette": "glashutte",
            "glashutte": "glashutte",
        }
        return aliases.get(normalized, normalized)

    @staticmethod
    def _map_condition(condition: Optional[str]) -> int:
        if not condition:
            return APP_CONFIG.muv_default_condition
        text = condition.casefold()
        if "unworn" in text or "neu" in text:
            return 1
        if "mint" in text or "★★★★★" in condition:
            return 2
        if "fair" in text or "★★★" in condition:
            return 4
        if "poor" in text or "★" == condition.strip():
            return 5
        return APP_CONFIG.muv_default_condition

    @staticmethod
    def _map_scope(has_box: Optional[bool], has_papers: Optional[bool]) -> int:
        if has_box and has_papers:
            return 4
        if has_papers:
            return 3
        if has_box:
            return 2
        return 1

    @staticmethod
    def _int_or_none(value: Any) -> Optional[int]:
        try:
            if value is None or value == "":
                return None
            return int(str(value)[:4])
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _listing_summary(listing: Dict[str, Any]) -> Dict[str, Any]:
        keys = [
            "title",
            "url",
            "site_name",
            "brand",
            "model",
            "reference",
            "year",
            "price",
            "price_display",
            "currency",
            "condition",
            "has_box",
            "has_papers",
            "image_url",
        ]
        return {key: listing.get(key) for key in keys}

    @classmethod
    def _watch_from_listing(cls, listing: Dict[str, Any]) -> WatchData:
        price = cls._decimal_or_none(listing.get("price"))
        return WatchData(
            title=listing.get("title") or "Unknown Watch",
            url=listing.get("url") or listing.get("muv_url") or "",
            site_name=listing.get("site_name") or "MUV",
            site_key=listing.get("site_key") or "muv",
            brand=listing.get("brand"),
            model=listing.get("model"),
            reference=listing.get("reference"),
            year=listing.get("year"),
            price=price,
            currency=listing.get("currency") or "EUR",
            price_display=listing.get("price_display"),
            image_url=listing.get("image_url") or cls._first_image_url(listing),
            condition=listing.get("condition"),
            has_box=listing.get("has_box"),
            has_papers=listing.get("has_papers"),
            case_material=listing.get("case_material"),
            diameter=listing.get("diameter"),
        )

    @staticmethod
    def _listing_from_offer(offer: Dict[str, Any]) -> Dict[str, Any]:
        watches = offer.get("watches") or []
        primary = watches[0] if watches else {}
        title = " ".join(
            part
            for part in [
                primary.get("brand"),
                primary.get("model"),
                primary.get("reference"),
            ]
            if part
        )
        return {
            "title": title or "MUV offer",
            "url": offer.get("source_url") or offer.get("muv_url") or "",
            "site_name": "MUV",
            "site_key": "muv",
            "brand": primary.get("brand"),
            "model": primary.get("model"),
            "reference": primary.get("reference"),
            "condition": primary.get("condition"),
            "image_url": primary.get("picture_url"),
            "currency": offer.get("currency") or "EUR",
        }

    @staticmethod
    def _first_image_url(listing: Dict[str, Any]) -> Optional[str]:
        image_urls = listing.get("image_urls") or []
        if isinstance(image_urls, list):
            return next((url for url in image_urls if url), None)
        return None

    @staticmethod
    def _decimal_or_none(value: Any) -> Optional[Decimal]:
        if value in (None, ""):
            return None
        try:
            return Decimal(str(value).replace(",", ""))
        except (InvalidOperation, ValueError):
            return None

    @classmethod
    def _offer_price_display(cls, offer: Dict[str, Any]) -> Optional[str]:
        price = (
            offer.get("price")
            or offer.get("purchase_price")
            or offer.get("offer")
            or offer.get("amount")
        )
        if not price:
            return None
        currency = offer.get("currency") or "EUR"
        if currency == "EUR":
            return f"€{price}"
        if currency == "USD":
            return f"${price}"
        return f"{price} {currency}"

    @staticmethod
    def _format_offer(offer: Dict[str, Any]) -> str:
        price = (
            offer.get("price")
            or offer.get("purchase_price")
            or offer.get("offer")
            or offer.get("amount")
        )
        currency = offer.get("currency") or "EUR"
        parts = []
        if offer.get("status"):
            parts.append(f"Status: **{offer['status']}**")
        if price:
            parts.append(f"**{price} {currency}**")
        for watch in offer.get("watches") or []:
            label = " ".join(
                part
                for part in [
                    watch.get("brand"),
                    watch.get("model"),
                    watch.get("reference"),
                ]
                if part
            )
            watch_line = label or "MUV watch"
            if watch.get("price_display"):
                watch_line += f" - {watch['price_display']} {currency}"
            elif watch.get("status"):
                watch_line += f" - {watch['status']}"
            parts.append(watch_line)
        if offer.get("offer_expiry_date_utc"):
            parts.append(f"Valid until: {offer['offer_expiry_date_utc']}")
        if offer.get("message"):
            parts.append(str(offer["message"]))
        if offer.get("muv_url"):
            parts.append(f"[Open MUV offer]({offer['muv_url']})")
        return "\n".join(parts)

    @staticmethod
    def _format_money(value: Any) -> Optional[str]:
        if value is None:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return str(value)
        return f"{number:,.0f}"

    @staticmethod
    def _offer_message(offer: Dict[str, Any]) -> str:
        status = offer.get("status")
        watches = offer.get("watches") or []
        primary = watches[0] if watches else {}
        name = " ".join(
            part for part in [primary.get("brand"), primary.get("model")] if part
        )

        if status == "offered" and offer.get("price"):
            return f"MUV offered {offer['price']} {offer.get('currency', 'EUR')} for {name or 'the watch'}."
        if status == "rejected":
            return f"MUV rejected {name or 'the submitted watch'}."
        if status == "pending":
            return "MUV has not reviewed this request yet."
        if status == "canceled":
            return "The MUV request is canceled."
        return "MUV offer link was reviewed."

    @staticmethod
    def _match_to_dict(match: MUVMatch) -> Dict[str, Any]:
        return {
            "brand_name": match.brand_name,
            "brand_id": match.brand_id,
            "model_name": match.model_name,
            "model_id": match.model_id,
            "ref_mp": match.ref_mp,
            "confidence": match.confidence,
        }

    @staticmethod
    def _build_comment(listing: Dict[str, Any]) -> str:
        parts = [
            "Automated listing import from luxury-watch-monitor.",
            f"Original listing: {listing.get('url')}",
        ]
        if listing.get("price_display") or listing.get("price"):
            parts.append(
                f"Listing price: {listing.get('price_display') or listing.get('price')}"
            )
        if listing.get("reference"):
            parts.append(f"Reference: {listing.get('reference')}")
        return "\n".join(parts)
