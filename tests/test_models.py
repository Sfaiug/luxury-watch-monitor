"""Tests for data models."""

import pytest
from decimal import Decimal
from datetime import datetime
from unittest.mock import patch, Mock

from models import WatchData, ScrapingSession


class TestWatchData:
    """Test WatchData model."""
    
    def test_watch_data_initialization(self):
        """Test basic WatchData initialization."""
        watch = WatchData(
            title="Rolex Submariner",
            url="https://example.com/watch",
            site_name="Test Site",
            site_key="test_site",
            price=Decimal("8500.00"),
            currency="EUR",
            brand="Rolex"
        )
        
        assert watch.title == "Rolex Submariner"
        assert watch.url == "https://example.com/watch"
        assert watch.site_name == "Test Site"
        assert watch.site_key == "test_site"
        assert watch.price == Decimal("8500.00")
        assert watch.currency == "EUR"
        assert watch.brand == "Rolex"
        assert watch.composite_id is not None
        assert len(watch.composite_id) == 32  # MD5 hash length
    
    def test_composite_id_generation(self):
        """Test composite ID generation and uniqueness."""
        watch1 = WatchData(
            title="Rolex Submariner",
            url="https://example.com/watch1",
            site_name="Test Site",
            site_key="test_site",
            brand="Rolex",
            model="Submariner",
            price=Decimal("8500")
        )
        watch2 = WatchData(
            title="Rolex Submariner",
            url="https://example.com/watch2",
            site_name="Test Site",
            site_key="test_site",
            brand="Rolex",
            model="Submariner",
            price=Decimal("8500")
        )
        watch3 = WatchData(
            title="Omega Speedmaster",
            url="https://example.com/watch3", 
            site_name="Test Site",
            site_key="test_site",
            brand="Omega",
            model="Speedmaster",
            price=Decimal("4000")
        )
        
        # Same watches should have same ID
        assert watch1.composite_id == watch2.composite_id
        
        # Different watches should have different IDs
        assert watch1.composite_id != watch3.composite_id
    
    def test_text_cleaning(self):
        """Test text cleaning functionality."""
        watch = WatchData(
            title="  Rolex   Submariner  \n\t  ",
            url="https://example.com/watch",
            site_name="Test Site",
            site_key="test_site",
            brand="  ROLEX  ",
            model="  Submariner  Date  "
        )
        
        assert watch.title == "Rolex Submariner"
        assert watch.brand == "ROLEX"
        assert watch.model == "Submariner Date"
    
    def test_price_display_formatting(self):
        """Test price display formatting."""
        watch = WatchData(
            title="Test Watch",
            url="https://example.com/watch",
            site_name="Test Site",
            site_key="test_site",
            price=Decimal("8500.00"),
            currency="EUR"
        )
        
        assert watch.price_display == "€8.500"
        
        # Test USD formatting  
        watch_usd = WatchData(
            title="Test Watch USD",
            url="https://example.com/watch",
            site_name="Test Site",
            site_key="test_site",
            price=Decimal("10000.00"),
            currency="USD"
        )
        
        assert watch_usd.price_display == "$10.000"
    
    @patch('models.APP_CONFIG')
    def test_to_discord_embed(self, mock_config):
        """Test Discord embed generation."""
        # Mock the emoji config
        mock_config.emoji_config = {
            "price": "💰",
            "reference": "#️⃣",
            "search": "🔍",
            "year": "🗓️",
            "condition": "⭐",
            "box": "📦",
            "papers": "📄",
            "material": "🔩",
            "diameter": "📏",
            "check": "✅",
            "cross": "❌",
            "question": "❓"
        }
        
        watch = WatchData(
            title="Rolex Submariner",
            url="https://example.com/watch",
            site_name="Test Site",
            site_key="test_site",
            brand="Rolex",
            model="Submariner",
            reference="116610LN",
            year="2020",
            price=Decimal("8500.00"),
            currency="EUR",
            image_url="https://example.com/image.jpg",
            condition="⭐⭐⭐⭐⭐",
            has_box=True,
            has_papers=True,
            case_material="Steel",
            diameter="40mm"
        )
        
        embed = watch.to_discord_embed(color=0x00FF00)
        
        assert embed["title"].startswith("Rolex")
        assert embed["url"] == "https://example.com/watch"
        assert embed["color"] == 0x00FF00
        assert embed["image"]["url"] == "https://example.com/image.jpg"
        assert "Test Site" in embed["footer"]["text"]
        
        # Check that fields are present
        assert len(embed["fields"]) > 0
        field_names = [field["name"] for field in embed["fields"]]
        assert any("Price" in name for name in field_names)
    
    @patch('models.APP_CONFIG')
    def test_chrono24_search_url(self, mock_config):
        """Test Chrono24 search URL generation."""
        mock_config.emoji_config = {"question": "❓"}
        
        watch = WatchData(
            title="Rolex Submariner",
            url="https://example.com/watch",
            site_name="Test Site",
            site_key="test_site",
            brand="Rolex",
            model="Submariner",
            reference="116610LN"
        )
        
        search_url = watch.chrono24_search_url
        
        assert "chrono24.de/search" in search_url
        assert "Rolex" in search_url or "rolex" in search_url
        assert "Submariner" in search_url or "submariner" in search_url
    
    def test_embed_title_truncation(self):
        """Test embed title truncation for long titles."""
        long_title = "A" * 300  # Longer than 250 character limit
        
        watch = WatchData(
            title=long_title,
            url="https://example.com/watch",
            site_name="Test Site",
            site_key="test_site"
        )
        
        # Test the internal title building method
        embed_title = watch._build_embed_title()
        assert len(embed_title) <= 253  # 250 + "..."


class TestScrapingSession:
    """Test ScrapingSession model."""
    
    def test_scraping_session_initialization(self):
        """Test ScrapingSession initialization."""
        session = ScrapingSession(session_id="test-123")
        
        assert session.session_id == "test-123"
        assert session.started_at is not None
        assert session.ended_at is None
        assert session.sites_scraped == 0
        assert session.total_watches_found == 0
        assert session.total_new_watches == 0 
        assert session.notifications_sent == 0
        assert session.errors_encountered == 0
        assert len(session.site_stats) == 0
    
    def test_add_site_result(self):
        """Test adding site results to session."""
        session = ScrapingSession(session_id="test-123")
        
        session.add_site_result(
            site_key="site1",
            total_found=10,
            new_found=3,
            notifications=2,
            errors=0
        )
        
        assert session.sites_scraped == 1
        assert session.total_watches_found == 10
        assert session.total_new_watches == 3
        assert session.notifications_sent == 2
        assert session.errors_encountered == 0
        assert "site1" in session.site_stats
        assert session.site_stats["site1"]["total_found"] == 10
        assert session.site_stats["site1"]["new_found"] == 3
    
    def test_multiple_site_results(self):
        """Test adding multiple site results."""
        session = ScrapingSession(session_id="test-multi")
        
        # Add results for multiple sites
        session.add_site_result("site1", 10, 3, 2, 0)
        session.add_site_result("site2", 15, 5, 4, 1)
        session.add_site_result("site3", 8, 1, 1, 0)
        
        assert session.sites_scraped == 3
        assert session.total_watches_found == 33  # 10 + 15 + 8
        assert session.total_new_watches == 9     # 3 + 5 + 1
        assert session.notifications_sent == 7    # 2 + 4 + 1
        assert session.errors_encountered == 1    # 0 + 1 + 0
        assert len(session.site_stats) == 3
    
    def test_session_finalization(self):
        """Test session finalization."""
        session = ScrapingSession(session_id="test-123")
        
        # Add some delay to test duration calculation
        import time
        time.sleep(0.01)
        
        session.finalize()
        
        assert session.ended_at is not None
        assert session.duration_seconds is not None
        assert session.duration_seconds > 0
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        session = ScrapingSession(session_id="test-dict")
        session.add_site_result("site1", 10, 3, 2, 0)
        session.finalize()
        
        session_dict = session.to_dict()
        
        assert session_dict["session_id"] == "test-dict"
        assert "started_at" in session_dict
        assert "ended_at" in session_dict
        assert "duration_seconds" in session_dict
        assert session_dict["sites_scraped"] == 1
        assert session_dict["total_watches_found"] == 10
        assert session_dict["total_new_watches"] == 3
        assert session_dict["notifications_sent"] == 2
        assert session_dict["errors_encountered"] == 0
        assert "site_stats" in session_dict
        assert "site1" in session_dict["site_stats"]
    
    def test_session_id_generation(self):
        """Test automatic session ID generation."""
        session1 = ScrapingSession()
        session2 = ScrapingSession()
        
        # Session IDs should be different
        assert session1.session_id != session2.session_id
        
        # Session IDs should follow the expected format (YYYYMMDD_HHMMSS)
        assert len(session1.session_id) == 15  # YYYYMMDD_HHMMSS format
        assert "_" in session1.session_id