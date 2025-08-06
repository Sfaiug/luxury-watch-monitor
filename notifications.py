"""Discord notification system for watch monitor application."""

import asyncio
from datetime import datetime
from typing import List, Dict, Any
import aiohttp
import logging

from config import APP_CONFIG, SiteConfig
from models import WatchData
from logging_config import PerformanceLogger


class NotificationManager:
    """Manages Discord webhook notifications."""
    
    def __init__(self, session: aiohttp.ClientSession, logger: logging.Logger):
        """
        Initialize notification manager.
        
        Args:
            session: aiohttp session for requests
            logger: Logger instance
        """
        self.session = session
        self.logger = logger
    
    async def send_notifications(self, watches: List[WatchData], site_config: SiteConfig) -> int:
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
        if not webhook_url:
            self.logger.warning(
                f"No webhook URL configured for {site_config.name}. "
                f"Set environment variable: {site_config.webhook_env_var}"
            )
            return 0
        
        # Send notifications with rate limiting
        success_count = 0
        
        for i, watch in enumerate(watches):
            try:
                # Convert watch to Discord embed
                embed = watch.to_discord_embed(site_config.color)
                
                # Send notification
                success = await self._send_single_notification(
                    webhook_url,
                    embed,
                    site_config.name,
                    watch.title
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
        webhook_url: str,
        embed: Dict[str, Any],
        site_name: str,
        watch_title: str
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
        
        with PerformanceLogger(self.logger, f"sending notification for '{watch_title}'"):
            try:
                timeout = aiohttp.ClientTimeout(total=15)
                
                async with self.session.post(
                    webhook_url,
                    json=payload,
                    timeout=timeout
                ) as response:
                    
                    if response.status == 204:
                        self.logger.debug(f"Successfully sent notification for '{watch_title}'")
                        return True
                    
                    # Handle rate limiting
                    if response.status == 429:
                        retry_after = int(response.headers.get('X-RateLimit-Reset-After', 5))
                        self.logger.warning(
                            f"Discord rate limit hit. Waiting {retry_after}s before retry"
                        )
                        await asyncio.sleep(retry_after)
                        
                        # Retry once
                        async with self.session.post(
                            webhook_url,
                            json=payload,
                            timeout=timeout
                        ) as retry_response:
                            if retry_response.status == 204:
                                return True
                    
                    # Log error response
                    error_text = await response.text()
                    self.logger.error(
                        f"Discord webhook error for {site_name}: "
                        f"Status {response.status}, Response: {error_text}"
                    )
                    return False
                    
            except asyncio.TimeoutError:
                self.logger.error(f"Timeout sending notification to {site_name}")
                return False
            except aiohttp.ClientError as e:
                self.logger.error(f"Network error sending notification to {site_name}: {e}")
                return False
            except Exception as e:
                self.logger.exception(f"Unexpected error sending notification to {site_name}: {e}")
                return False
    
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
                    "inline": False
                }
            ],
            "footer": {
                "text": f"Test performed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            }
        }
        
        return await self._send_single_notification(
            webhook_url,
            test_embed,
            "Test",
            "Test Notification"
        )