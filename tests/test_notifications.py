"""Tests for notification system."""

import pytest
import asyncio
import json
from unittest.mock import AsyncMock, Mock, patch
from decimal import Decimal

from notifications import NotificationManager
from models import WatchData
from config import SiteConfig


class TestNotificationManager:
    """Test NotificationManager functionality."""
    
    def test_notification_manager_initialization(self, mock_aiohttp_session, mock_logger):
        """Test NotificationManager initialization."""
        manager = NotificationManager(mock_aiohttp_session, mock_logger)
        
        assert manager.session == mock_aiohttp_session
        assert manager.logger == mock_logger
    
    @pytest.mark.asyncio
    async def test_send_notifications_empty_list(self, mock_notification_manager, test_site_config):
        """Test sending notifications with empty watch list.""" 
        result = await mock_notification_manager.send_notifications([], test_site_config)
        
        assert result == 0
    
    @pytest.mark.asyncio
    async def test_send_notifications_disabled(self, mock_aiohttp_session, mock_logger, sample_watch_list, test_site_config):
        """Test sending notifications when notifications are disabled."""
        with patch('notifications.APP_CONFIG') as mock_config:
            mock_config.enable_notifications = False
            
            manager = NotificationManager(mock_aiohttp_session, mock_logger)
            result = await manager.send_notifications(sample_watch_list, test_site_config)
        
        assert result == 0
        mock_logger.info.assert_called_with("Notifications are disabled in configuration")
    
    @pytest.mark.asyncio
    async def test_send_notifications_no_webhook_url(self, mock_aiohttp_session, mock_logger, sample_watch_list):
        """Test sending notifications when no webhook URL is configured."""
        site_config = SiteConfig(
            name="Test Site",
            key="test_site", 
            url="https://example.com",
            webhook_env_var="NONEXISTENT_WEBHOOK_URL",
            color=0x00FF00,
            base_url="https://example.com"
        )
        
        manager = NotificationManager(mock_aiohttp_session, mock_logger)
        result = await manager.send_notifications(sample_watch_list, site_config)
        
        assert result == 0
        mock_logger.warning.assert_called()
    
    @pytest.mark.asyncio
    async def test_send_notifications_success(self, mock_aiohttp_session, mock_logger, sample_watch_list, test_site_config):
        """Test successful notification sending."""
        # Mock webhook URL
        with patch.object(test_site_config, 'webhook_url', 'https://discord.com/api/webhooks/test/token'):
            manager = NotificationManager(mock_aiohttp_session, mock_logger)
            
            # Mock successful webhook response
            mock_response = AsyncMock()
            mock_response.status = 204
            mock_aiohttp_session.post.return_value.__aenter__.return_value = mock_response
            
            with patch('notifications.APP_CONFIG') as mock_config:
                mock_config.enable_notifications = True
                
                result = await manager.send_notifications(sample_watch_list, test_site_config)
        
        assert result == len(sample_watch_list)
        assert mock_aiohttp_session.post.call_count == len(sample_watch_list)
        mock_logger.info.assert_called()
    
    @pytest.mark.asyncio 
    async def test_send_notifications_with_failures(self, mock_aiohttp_session, mock_logger, sample_watch_list, test_site_config):
        """Test notification sending with some failures."""
        with patch.object(test_site_config, 'webhook_url', 'https://discord.com/api/webhooks/test/token'):
            manager = NotificationManager(mock_aiohttp_session, mock_logger)
            
            # Mock responses - first succeeds, second fails
            responses = []
            for i, watch in enumerate(sample_watch_list):
                mock_response = AsyncMock()
                mock_response.status = 204 if i == 0 else 400
                mock_response.text.return_value = "Bad Request" if i != 0 else ""
                responses.append(mock_response)
            
            mock_aiohttp_session.post.return_value.__aenter__.side_effect = responses
            
            with patch('notifications.APP_CONFIG') as mock_config:
                mock_config.enable_notifications = True
                
                result = await manager.send_notifications(sample_watch_list, test_site_config)
        
        # Only first notification should succeed
        assert result == 1
        mock_logger.error.assert_called()
    
    @pytest.mark.asyncio
    async def test_send_single_notification_success(self, mock_aiohttp_session, mock_logger):
        """Test sending a single notification successfully."""
        manager = NotificationManager(mock_aiohttp_session, mock_logger)
        
        mock_response = AsyncMock()
        mock_response.status = 204
        mock_aiohttp_session.post.return_value.__aenter__.return_value = mock_response
        
        embed = {"title": "Test Watch", "color": 0x00FF00}
        webhook_url = "https://discord.com/api/webhooks/test/token"
        
        result = await manager._send_single_notification(
            webhook_url, embed, "Test Site", "Test Watch"
        )
        
        assert result is True
        mock_aiohttp_session.post.assert_called_once()
        
        # Verify request was made with correct data
        call_args = mock_aiohttp_session.post.call_args
        assert call_args[0][0] == webhook_url
        assert call_args[1]["json"] == {"embeds": [embed]}
    
    @pytest.mark.asyncio
    async def test_send_single_notification_rate_limit(self, mock_aiohttp_session, mock_logger):
        """Test handling Discord rate limiting."""
        manager = NotificationManager(mock_aiohttp_session, mock_logger)
        
        # First response: rate limited
        rate_limit_response = AsyncMock()
        rate_limit_response.status = 429
        rate_limit_response.headers = {"X-RateLimit-Reset-After": "2"}
        
        # Second response: success
        success_response = AsyncMock()
        success_response.status = 204
        
        mock_aiohttp_session.post.return_value.__aenter__.side_effect = [
            rate_limit_response, success_response
        ]
        
        embed = {"title": "Test Watch", "color": 0x00FF00}
        webhook_url = "https://discord.com/api/webhooks/test/token"
        
        with patch('asyncio.sleep') as mock_sleep:
            result = await manager._send_single_notification(
                webhook_url, embed, "Test Site", "Test Watch"
            )
        
        assert result is True
        assert mock_aiohttp_session.post.call_count == 2
        mock_sleep.assert_called_once_with(2)  # Should wait for rate limit
        mock_logger.warning.assert_called()
    
    @pytest.mark.asyncio
    async def test_send_single_notification_permanent_failure(self, mock_aiohttp_session, mock_logger):
        """Test handling permanent notification failure."""
        manager = NotificationManager(mock_aiohttp_session, mock_logger)
        
        mock_response = AsyncMock()
        mock_response.status = 400
        mock_response.text.return_value = "Bad Request"
        mock_aiohttp_session.post.return_value.__aenter__.return_value = mock_response
        
        embed = {"title": "Test Watch", "color": 0x00FF00}
        webhook_url = "https://discord.com/api/webhooks/test/token"
        
        result = await manager._send_single_notification(
            webhook_url, embed, "Test Site", "Test Watch"
        )
        
        assert result is False
        mock_logger.error.assert_called()
    
    @pytest.mark.asyncio
    async def test_send_single_notification_timeout(self, mock_aiohttp_session, mock_logger):
        """Test handling request timeout."""
        manager = NotificationManager(mock_aiohttp_session, mock_logger)
        
        mock_aiohttp_session.post.side_effect = asyncio.TimeoutError()
        
        embed = {"title": "Test Watch", "color": 0x00FF00}
        webhook_url = "https://discord.com/api/webhooks/test/token"
        
        result = await manager._send_single_notification(
            webhook_url, embed, "Test Site", "Test Watch"
        )
        
        assert result is False
        mock_logger.error.assert_called_with("Timeout sending notification to Test Site")
    
    @pytest.mark.asyncio
    async def test_send_single_notification_network_error(self, mock_aiohttp_session, mock_logger):
        """Test handling network errors."""
        import aiohttp
        
        manager = NotificationManager(mock_aiohttp_session, mock_logger)
        
        mock_aiohttp_session.post.side_effect = aiohttp.ClientError("Network error")
        
        embed = {"title": "Test Watch", "color": 0x00FF00}
        webhook_url = "https://discord.com/api/webhooks/test/token"
        
        result = await manager._send_single_notification(
            webhook_url, embed, "Test Site", "Test Watch"
        )
        
        assert result is False
        mock_logger.error.assert_called()
    
    @pytest.mark.asyncio
    async def test_send_single_notification_unexpected_error(self, mock_aiohttp_session, mock_logger):
        """Test handling unexpected errors."""
        manager = NotificationManager(mock_aiohttp_session, mock_logger)
        
        mock_aiohttp_session.post.side_effect = Exception("Unexpected error")
        
        embed = {"title": "Test Watch", "color": 0x00FF00}
        webhook_url = "https://discord.com/api/webhooks/test/token"
        
        result = await manager._send_single_notification(
            webhook_url, embed, "Test Site", "Test Watch"
        )
        
        assert result is False
        mock_logger.exception.assert_called()
    
    @pytest.mark.asyncio
    async def test_test_webhook_success(self, mock_aiohttp_session, mock_logger):
        """Test webhook testing functionality."""
        manager = NotificationManager(mock_aiohttp_session, mock_logger)
        
        mock_response = AsyncMock()
        mock_response.status = 204
        mock_aiohttp_session.post.return_value.__aenter__.return_value = mock_response
        
        webhook_url = "https://discord.com/api/webhooks/test/token"
        
        result = await manager.test_webhook(webhook_url)
        
        assert result is True
        mock_aiohttp_session.post.assert_called_once()
        
        # Verify test embed was sent
        call_args = mock_aiohttp_session.post.call_args
        embed_data = call_args[1]["json"]["embeds"][0]
        assert "Test" in embed_data["title"]
        assert embed_data["color"] == 0x00FF00
        assert "working correctly" in embed_data["fields"][0]["value"]
    
    @pytest.mark.asyncio
    async def test_test_webhook_failure(self, mock_aiohttp_session, mock_logger):
        """Test webhook testing with failure."""
        manager = NotificationManager(mock_aiohttp_session, mock_logger)
        
        mock_response = AsyncMock()
        mock_response.status = 404
        mock_response.text.return_value = "Not Found"
        mock_aiohttp_session.post.return_value.__aenter__.return_value = mock_response
        
        webhook_url = "https://discord.com/api/webhooks/invalid/token"
        
        result = await manager.test_webhook(webhook_url)
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_notification_rate_limiting(self, mock_aiohttp_session, mock_logger, test_site_config):
        """Test rate limiting between notifications."""
        watches = [
            WatchData(
                title="Watch 1",
                url="https://example.com/watch1",
                site_name="Test Site",
                site_key="test_site"
            ),
            WatchData(
                title="Watch 2", 
                url="https://example.com/watch2",
                site_name="Test Site",
                site_key="test_site"
            ),
            WatchData(
                title="Watch 3",
                url="https://example.com/watch3", 
                site_name="Test Site",
                site_key="test_site"
            )
        ]
        
        with patch.object(test_site_config, 'webhook_url', 'https://discord.com/api/webhooks/test/token'):
            manager = NotificationManager(mock_aiohttp_session, mock_logger)
            
            # Mock successful responses
            mock_response = AsyncMock()
            mock_response.status = 204
            mock_aiohttp_session.post.return_value.__aenter__.return_value = mock_response
            
            with patch('notifications.APP_CONFIG') as mock_config:
                mock_config.enable_notifications = True
                
                with patch('asyncio.sleep') as mock_sleep:
                    result = await manager.send_notifications(watches, test_site_config)
        
        assert result == 3
        # Should sleep between notifications (but not after the last one)
        assert mock_sleep.call_count == 2
        mock_sleep.assert_called_with(1)  # 1 second delay
    
    @pytest.mark.asyncio
    async def test_notification_embed_generation(self, mock_aiohttp_session, mock_logger, test_site_config):
        """Test that notifications generate proper Discord embeds."""
        watch = WatchData(
            title="Rolex Submariner Date",
            url="https://example.com/watch",
            site_name="Test Site", 
            site_key="test_site",
            brand="Rolex",
            model="Submariner",
            reference="116610LN",
            price=Decimal("8500.00"),
            currency="EUR",
            year="2020",
            condition="★★★★★",
            has_box=True,
            has_papers=True,
            image_url="https://example.com/image.jpg"
        )
        
        with patch.object(test_site_config, 'webhook_url', 'https://discord.com/api/webhooks/test/token'):
            manager = NotificationManager(mock_aiohttp_session, mock_logger)
            
            # Mock the to_discord_embed method to verify it's called with correct color
            original_to_embed = watch.to_discord_embed
            watch.to_discord_embed = Mock(return_value=original_to_embed(test_site_config.color))
            
            mock_response = AsyncMock()
            mock_response.status = 204
            mock_aiohttp_session.post.return_value.__aenter__.return_value = mock_response
            
            with patch('notifications.APP_CONFIG') as mock_config:
                mock_config.enable_notifications = True
                
                result = await manager.send_notifications([watch], test_site_config)
        
        assert result == 1
        
        # Verify embed was generated with site color
        watch.to_discord_embed.assert_called_once_with(test_site_config.color)
        
        # Verify request payload
        call_args = mock_aiohttp_session.post.call_args
        payload = call_args[1]["json"]
        assert "embeds" in payload
        assert len(payload["embeds"]) == 1