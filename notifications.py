"""Discord notification system for watch monitor application."""

import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional
from urllib.parse import quote
import aiohttp
import logging

from config import APP_CONFIG, SiteConfig
from models import WatchData
from logging_config import PerformanceLogger
from action_store import ActionStore


class NotificationManager:
    """Manages Discord webhook notifications."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        logger: logging.Logger,
        action_store: Optional[ActionStore] = None,
    ):
        """
        Initialize notification manager.

        Args:
            session: aiohttp session for requests
            logger: Logger instance
        """
        self.session = session
        self.logger = logger
        self.action_store = action_store

    async def send_notifications(
        self, watches: List[WatchData], site_config: SiteConfig
    ) -> int:
        """
        Send Discord notifications for new watches.

        Args:
            watches: List of watches to notify about
            site_config: Site configuration with webhook URL

        Returns:
            Number of successful notifications sent
        """
        if not watches:
            return 0

        if not APP_CONFIG.enable_notifications:
            self.logger.info("Notifications are disabled in configuration")
            return 0

        webhook_url = site_config.webhook_url
        bot_channel_id = self._bot_channel_id(site_config)
        use_bot = self._can_send_with_bot(bot_channel_id)
        if not webhook_url and not use_bot:
            self.logger.warning(
                f"No Discord destination configured for {site_config.name}. "
                f"Set {site_config.webhook_env_var} or a Discord channel id."
            )
            return 0

        # Send notifications with rate limiting
        success_count = 0

        for i, watch in enumerate(watches):
            try:
                # Convert watch to Discord embed
                embed = watch.to_discord_embed(site_config.color)

                components = self._build_muv_components(
                    watch, use_link_button=not use_bot
                )

                # Send notification
                success = await self._send_single_notification(
                    webhook_url,
                    embed,
                    site_config.name,
                    watch.title,
                    components=components,
                    bot_channel_id=bot_channel_id if use_bot else None,
                )

                if success:
                    success_count += 1

                # Rate limit between notifications (except for last one)
                if i < len(watches) - 1:
                    await asyncio.sleep(1)

            except Exception as e:
                self.logger.error(f"Error sending notification for {watch.title}: {e}")

        self.logger.info(
            f"Sent {success_count}/{len(watches)} notifications for {site_config.name}"
        )

        return success_count

    async def _send_single_notification(
        self,
        webhook_url: Optional[str],
        embed: Dict[str, Any],
        site_name: str,
        watch_title: str,
        components: Optional[List[Dict[str, Any]]] = None,
        bot_channel_id: Optional[str] = None,
    ) -> bool:
        """
        Send a single Discord notification.

        Args:
            webhook_url: Discord webhook URL
            embed: Embed data dictionary
            site_name: Name of the site
            watch_title: Title of the watch (for logging)

        Returns:
            True if successful, False otherwise
        """
        payload = {"embeds": [embed]}
        if components:
            payload["components"] = components

        with PerformanceLogger(
            self.logger, f"sending notification for '{watch_title}'"
        ):
            try:
                timeout = aiohttp.ClientTimeout(total=15)
                if bot_channel_id and self._can_send_with_bot(bot_channel_id):
                    if await self._post_bot_message(
                        bot_channel_id, payload, site_name, watch_title, timeout
                    ):
                        return True

                    if webhook_url:
                        self.logger.warning(
                            f"Bot notification failed for {site_name}; falling back to webhook"
                        )
                        payload = self._webhook_fallback_payload(embed, components)

                if not webhook_url:
                    self.logger.error(f"No webhook URL available for {site_name}")
                    return False

                async with self.session.post(
                    webhook_url,
                    json=payload,
                    params={"with_components": "true"} if components else None,
                    timeout=timeout,
                ) as response:

                    if response.status == 204:
                        self.logger.debug(
                            f"Successfully sent notification for '{watch_title}'"
                        )
                        return True

                    # Handle rate limiting
                    if response.status == 429:
                        retry_after = int(
                            response.headers.get("X-RateLimit-Reset-After", 5)
                        )
                        self.logger.warning(
                            f"Discord rate limit hit. Waiting {retry_after}s before retry"
                        )
                        await asyncio.sleep(retry_after)

                        # Retry once
                        async with self.session.post(
                            webhook_url,
                            json=payload,
                            params={"with_components": "true"} if components else None,
                            timeout=timeout,
                        ) as retry_response:
                            if retry_response.status == 204:
                                return True

                    # Log error response (limit size to prevent memory accumulation)
                    error_text = await response.text()
                    error_text = error_text[:500] if error_text else "No error message"
                    self.logger.error(
                        f"Discord webhook error for {site_name}: "
                        f"Status {response.status}, Response: {error_text}"
                    )
                    return False

            except asyncio.TimeoutError:
                self.logger.error(f"Timeout sending notification to {site_name}")
                return False
            except aiohttp.ClientError as e:
                self.logger.error(
                    f"Network error sending notification to {site_name}: {e}"
                )
                return False
            except Exception as e:
                self.logger.exception(
                    f"Unexpected error sending notification to {site_name}: {e}"
                )
                return False
            finally:
                payload = None

    async def test_webhook(self, webhook_url: str) -> bool:
        """
        Test if a webhook URL is valid and accessible.

        Args:
            webhook_url: Discord webhook URL to test

        Returns:
            True if webhook is valid, False otherwise
        """
        test_embed = {
            "title": "🔔 Watch Monitor Test",
            "description": "This is a test notification from the watch monitor system.",
            "color": 0x00FF00,
            "fields": [
                {
                    "name": "Status",
                    "value": "✅ Webhook is working correctly!",
                    "inline": False,
                }
            ],
            "footer": {
                "text": f"Test performed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            },
        }

        return await self._send_single_notification(
            webhook_url, test_embed, "Test", "Test Notification"
        )

    def _build_muv_components(
        self, watch: WatchData, *, use_link_button: bool = True
    ) -> List[Dict[str, Any]] | None:
        """Create the MUV action button for Discord interaction webhooks."""
        if not APP_CONFIG.enable_muv_actions or not self.action_store:
            return None

        action_id = self.action_store.save_watch(watch)
        custom_id = ActionStore.custom_id(action_id, APP_CONFIG.action_token_secret)
        action_url = self._build_muv_action_url(custom_id)
        if action_url and use_link_button:
            button = {
                "type": 2,
                "style": 5,
                "label": APP_CONFIG.muv_action_label,
                "url": action_url,
            }
        else:
            button = {
                "type": 2,
                "style": 1,
                "label": APP_CONFIG.muv_action_label,
                "custom_id": custom_id,
            }

        return [
            {
                "type": 1,
                "components": [button],
            }
        ]

    def _bot_channel_id(self, site_config: SiteConfig) -> Optional[str]:
        channel_id = site_config.discord_channel_id or getattr(
            APP_CONFIG, "discord_alert_channel_id", ""
        )
        return channel_id.strip() if isinstance(channel_id, str) else None

    @staticmethod
    def _can_send_with_bot(channel_id: Optional[str]) -> bool:
        token = getattr(APP_CONFIG, "discord_bot_token", "")
        return bool(token and channel_id)

    async def _post_bot_message(
        self,
        channel_id: str,
        payload: Dict[str, Any],
        site_name: str,
        watch_title: str,
        timeout: aiohttp.ClientTimeout,
    ) -> bool:
        api_base = getattr(
            APP_CONFIG, "discord_api_base_url", "https://discord.com/api/v10"
        ).rstrip("/")
        url = f"{api_base}/channels/{channel_id}/messages"
        headers = {
            "Authorization": f"Bot {APP_CONFIG.discord_bot_token}",
            "Content-Type": "application/json",
            "User-Agent": "DiscordBot (https://atlas.hopcomp.com, 1.0)",
        }

        async with self.session.post(
            url,
            json=payload,
            headers=headers,
            timeout=timeout,
        ) as response:
            if response.status in (200, 201):
                self.logger.debug(
                    f"Successfully sent bot notification for '{watch_title}'"
                )
                return True

            if response.status == 429:
                retry_after = int(response.headers.get("X-RateLimit-Reset-After", 5))
                self.logger.warning(
                    f"Discord bot rate limit hit. Waiting {retry_after}s before retry"
                )
                await asyncio.sleep(retry_after)
                async with self.session.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=timeout,
                ) as retry_response:
                    if retry_response.status in (200, 201):
                        return True
                    error_text = await retry_response.text()
                    error_text = error_text[:500] if error_text else "No error message"
                    self.logger.error(
                        f"Discord bot error for {site_name}: "
                        f"Status {retry_response.status}, Response: {error_text}"
                    )
                    return False

            error_text = await response.text()
            error_text = error_text[:500] if error_text else "No error message"
            self.logger.error(
                f"Discord bot error for {site_name}: "
                f"Status {response.status}, Response: {error_text}"
            )
            return False

    @staticmethod
    def _webhook_fallback_payload(
        embed: Dict[str, Any], components: Optional[List[Dict[str, Any]]]
    ) -> Dict[str, Any]:
        payload = {"embeds": [embed]}
        fallback_components = NotificationManager._webhook_fallback_components(
            components
        )
        if fallback_components:
            payload["components"] = fallback_components
        return payload

    @staticmethod
    def _webhook_fallback_components(
        components: Optional[List[Dict[str, Any]]],
    ) -> Optional[List[Dict[str, Any]]]:
        if not components:
            return None

        fallback = []
        for row in components:
            copied_row = dict(row)
            copied_buttons = []
            for button in row.get("components") or []:
                copied_button = dict(button)
                custom_id = copied_button.get("custom_id")
                if custom_id and copied_button.get("type") == 2:
                    action_url = NotificationManager._build_muv_action_url(custom_id)
                    if action_url:
                        copied_button.pop("custom_id", None)
                        copied_button["style"] = 5
                        copied_button["url"] = action_url
                copied_buttons.append(copied_button)
            copied_row["components"] = copied_buttons
            fallback.append(copied_row)
        return fallback

    @staticmethod
    def _build_muv_action_url(custom_id: str) -> Optional[str]:
        """Build a signed VM link-button URL when configured."""
        if APP_CONFIG.muv_http_actions_enabled is not True:
            return None
        base_config = APP_CONFIG.muv_action_base_url
        base_url = (
            base_config.strip().rstrip("/") if isinstance(base_config, str) else ""
        )
        if not base_url:
            return None
        path_config = APP_CONFIG.muv_action_web_path
        path = "/" + (
            path_config.strip("/") if isinstance(path_config, str) else "muv/actions"
        )
        return f"{base_url}{path}/{quote(custom_id, safe='')}"
