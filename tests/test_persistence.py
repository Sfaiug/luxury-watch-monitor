"""Tests for persistence layer."""

import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, mock_open
from datetime import datetime, timedelta

from persistence import PersistenceManager
from models import ScrapingSession


class TestPersistenceManager:
    """Test PersistenceManager functionality."""
    
    def test_persistence_manager_initialization(self, mock_logger, temp_dir):
        """Test PersistenceManager initialization."""
        with patch('persistence.APP_CONFIG') as mock_config:
            mock_config.seen_watches_file = str(temp_dir / "seen_watches.json")
            mock_config.session_history_file = str(temp_dir / "session_history.json")
            
            manager = PersistenceManager(mock_logger)
            
            assert manager.logger == mock_logger
            assert manager.seen_items_file.name == "seen_watches.json"
            assert manager.session_history_file.name == "session_history.json"
    
    def test_load_seen_items_nonexistent_file(self, test_persistence_manager):
        """Test loading seen items when file doesn't exist."""
        result = test_persistence_manager.load_seen_items()
        
        assert result == {}
        test_persistence_manager.logger.info.assert_called_with(
            "Seen items file does not exist, starting fresh"
        )
    
    def test_load_seen_items_success(self, test_persistence_manager, temp_dir):
        """Test successful loading of seen items.""" 
        # Create test data file
        test_data = {
            "site1": ["id1", "id2", "id3"],
            "site2": ["id4", "id5"]
        }
        
        seen_file = temp_dir / "test_seen_watches.json"
        with open(seen_file, 'w') as f:
            json.dump(test_data, f)
        
        # Update the manager's file path
        test_persistence_manager.seen_items_file = seen_file
        
        result = test_persistence_manager.load_seen_items()
        
        assert len(result) == 2
        assert "site1" in result
        assert "site2" in result
        assert result["site1"] == {"id1", "id2", "id3"}  # Lists converted to sets
        assert result["site2"] == {"id4", "id5"}
        
        test_persistence_manager.logger.info.assert_called_with(
            f"Loaded seen items: 5 total"
        )
    
    def test_load_seen_items_empty_file(self, test_persistence_manager, temp_dir):
        """Test loading seen items from empty file."""
        seen_file = temp_dir / "test_seen_watches.json"
        seen_file.touch()  # Create empty file
        
        test_persistence_manager.seen_items_file = seen_file
        
        result = test_persistence_manager.load_seen_items()
        
        assert result == {}
        test_persistence_manager.logger.warning.assert_called_with(
            "Seen items file is empty"
        )
    
    def test_load_seen_items_json_error(self, test_persistence_manager, temp_dir):
        """Test loading seen items with JSON error.""" 
        seen_file = temp_dir / "test_seen_watches.json"
        with open(seen_file, 'w') as f:
            f.write("invalid json {")
        
        test_persistence_manager.seen_items_file = seen_file
        
        result = test_persistence_manager.load_seen_items()
        
        assert result == {}
        test_persistence_manager.logger.error.assert_called()
    
    def test_save_seen_items_success(self, test_persistence_manager, temp_dir):
        """Test successful saving of seen items."""
        test_data = {
            "site1": {"id1", "id2", "id3"},
            "site2": {"id4", "id5"}
        }
        
        seen_file = temp_dir / "test_seen_watches.json"
        test_persistence_manager.seen_items_file = seen_file
        
        test_persistence_manager.save_seen_items(test_data)
        
        # Verify file was created and contains correct data
        assert seen_file.exists()
        with open(seen_file, 'r') as f:
            saved_data = json.load(f)
        
        # Sets should be converted to lists for JSON serialization
        assert "site1" in saved_data
        assert "site2" in saved_data
        assert set(saved_data["site1"]) == {"id1", "id2", "id3"}
        assert set(saved_data["site2"]) == {"id4", "id5"}
        
        test_persistence_manager.logger.debug.assert_called_with(
            "Saved seen items successfully"
        )
    
    def test_save_seen_items_with_size_limit(self, test_persistence_manager, temp_dir):
        """Test saving seen items with size limit enforcement.""" 
        # Create data that exceeds the limit
        large_item_set = {f"id{i}" for i in range(2000)}  # Larger than limit
        test_data = {
            "site1": large_item_set,
            "site2": {"id1", "id2"}
        }
        
        seen_file = temp_dir / "test_seen_watches.json"
        test_persistence_manager.seen_items_file = seen_file
        
        with patch('persistence.APP_CONFIG') as mock_config:
            mock_config.max_seen_items_per_site = 1000
            
            test_persistence_manager.save_seen_items(test_data)
        
        # Verify file was created
        assert seen_file.exists()
        with open(seen_file, 'r') as f:
            saved_data = json.load(f)
        
        # site1 should be truncated
        assert len(saved_data["site1"]) == 1000
        assert len(saved_data["site2"]) == 2
        
        # Verify warning was logged
        test_persistence_manager.logger.warning.assert_called()
    
    def test_save_seen_items_error(self, test_persistence_manager):
        """Test saving seen items with file error."""
        test_data = {"site1": {"id1"}}
        
        # Set invalid path
        test_persistence_manager.seen_items_file = Path("/root/invalid/path.json")
        
        test_persistence_manager.save_seen_items(test_data)
        
        test_persistence_manager.logger.error.assert_called()
    
    def test_load_session_history_success(self, test_persistence_manager, temp_dir):
        """Test successful loading of session history."""
        test_sessions = [
            {
                "session_id": "session1",
                "started_at": datetime.now().isoformat(),
                "ended_at": datetime.now().isoformat(),
                "total_new_watches": 5
            },
            {
                "session_id": "session2", 
                "started_at": datetime.now().isoformat(),
                "ended_at": datetime.now().isoformat(),
                "total_new_watches": 3
            }
        ]
        
        history_file = temp_dir / "test_session_history.json"
        with open(history_file, 'w') as f:
            json.dump(test_sessions, f)
        
        test_persistence_manager.session_history_file = history_file
        
        result = test_persistence_manager.load_session_history()
        
        assert len(result) == 2
        assert result[0]["session_id"] == "session1"
        assert result[1]["session_id"] == "session2"
    
    def test_load_session_history_nonexistent_file(self, test_persistence_manager):
        """Test loading session history when file doesn't exist."""
        result = test_persistence_manager.load_session_history()
        assert result == []
    
    def test_load_session_history_empty_file(self, test_persistence_manager, temp_dir):
        """Test loading session history from empty file."""
        history_file = temp_dir / "test_session_history.json"
        history_file.touch()
        
        test_persistence_manager.session_history_file = history_file
        
        result = test_persistence_manager.load_session_history()
        assert result == []
    
    def test_save_session_success(self, test_persistence_manager, temp_dir):
        """Test successful saving of session."""
        session = ScrapingSession(session_id="test-session")
        session.add_site_result("site1", 10, 3, 2, 0)
        session.finalize()
        
        history_file = temp_dir / "test_session_history.json"
        test_persistence_manager.session_history_file = history_file
        
        test_persistence_manager.save_session(session)
        
        # Verify file was created and contains session data
        assert history_file.exists()
        with open(history_file, 'r') as f:
            saved_data = json.load(f)
        
        assert len(saved_data) == 1
        assert saved_data[0]["session_id"] == "test-session"
        assert saved_data[0]["total_new_watches"] == 3
        
        test_persistence_manager.logger.info.assert_called_with(
            f"Saved session test-session to history"
        )
    
    def test_save_session_with_retention(self, test_persistence_manager, temp_dir):
        """Test session saving with retention policy."""
        # Create old session data
        old_session = {
            "session_id": "old-session",
            "started_at": (datetime.now() - timedelta(days=60)).isoformat(),
            "total_new_watches": 1
        }
        recent_session = {
            "session_id": "recent-session", 
            "started_at": (datetime.now() - timedelta(days=5)).isoformat(),
            "total_new_watches": 2
        }
        
        history_file = temp_dir / "test_session_history.json"
        with open(history_file, 'w') as f:
            json.dump([old_session, recent_session], f)
        
        test_persistence_manager.session_history_file = history_file
        
        # Add new session
        new_session = ScrapingSession(session_id="new-session")
        new_session.finalize()
        
        with patch('persistence.APP_CONFIG') as mock_config:
            mock_config.session_history_retention_days = 30
            
            test_persistence_manager.save_session(new_session)
        
        # Verify old session was removed
        with open(history_file, 'r') as f:
            saved_data = json.load(f)
        
        session_ids = [s["session_id"] for s in saved_data]
        assert "old-session" not in session_ids  # Should be removed
        assert "recent-session" in session_ids   # Should be kept  
        assert "new-session" in session_ids      # Should be added
    
    def test_save_session_error(self, test_persistence_manager):
        """Test session saving with error."""
        session = ScrapingSession(session_id="test-session")
        session.finalize()
        
        # Mock load_session_history to raise an exception
        test_persistence_manager.load_session_history = Mock(side_effect=Exception("Load error"))
        
        test_persistence_manager.save_session(session) 
        
        test_persistence_manager.logger.error.assert_called()
    
    def test_get_session_statistics_success(self, test_persistence_manager, temp_dir):
        """Test getting session statistics."""
        # Create test session data
        sessions = []
        base_time = datetime.now() - timedelta(days=3)
        
        for i in range(5):
            session_data = {
                "session_id": f"session{i}",
                "started_at": (base_time + timedelta(hours=i)).isoformat(),
                "ended_at": (base_time + timedelta(hours=i, minutes=30)).isoformat(),
                "duration_seconds": 1800.0,
                "total_watches_found": 10 + i,
                "total_new_watches": 2 + i,
                "notifications_sent": 1 + i,
                "errors_encountered": 0 if i < 4 else 1
            }
            sessions.append(session_data)
        
        history_file = temp_dir / "test_session_history.json"
        with open(history_file, 'w') as f:
            json.dump(sessions, f)
        
        test_persistence_manager.session_history_file = history_file
        
        stats = test_persistence_manager.get_session_statistics(days=7)
        
        assert stats["total_sessions"] == 5
        assert stats["total_watches_found"] == 60  # 10+11+12+13+14
        assert stats["total_new_watches"] == 20    # 2+3+4+5+6
        assert stats["total_notifications"] == 15  # 1+2+3+4+5
        assert stats["success_rate"] == 80.0      # 4 successful out of 5
        assert stats["average_duration"] == 1800.0
        assert stats["period_days"] == 7
    
    def test_get_session_statistics_no_data(self, test_persistence_manager):
        """Test getting statistics with no session data."""
        stats = test_persistence_manager.get_session_statistics(days=7)
        
        expected = {
            "total_sessions": 0,
            "total_watches_found": 0,
            "total_new_watches": 0,
            "total_notifications": 0,
            "success_rate": 0.0,
            "average_duration": 0.0
        }
        
        for key, value in expected.items():
            assert stats[key] == value
    
    def test_get_session_statistics_filtered_by_date(self, test_persistence_manager, temp_dir):
        """Test statistics filtering by date range."""
        # Create sessions with different dates
        sessions = [
            {
                "session_id": "old-session",
                "started_at": (datetime.now() - timedelta(days=10)).isoformat(),
                "total_new_watches": 1,
                "errors_encountered": 0
            },
            {
                "session_id": "recent-session",
                "started_at": (datetime.now() - timedelta(days=2)).isoformat(), 
                "total_new_watches": 2,
                "errors_encountered": 0
            }
        ]
        
        history_file = temp_dir / "test_session_history.json"
        with open(history_file, 'w') as f:
            json.dump(sessions, f)
        
        test_persistence_manager.session_history_file = history_file
        
        # Get stats for last 7 days - should only include recent session
        stats = test_persistence_manager.get_session_statistics(days=7)
        
        assert stats["total_sessions"] == 1
        assert stats["total_new_watches"] == 2
    
    def test_get_session_statistics_error(self, test_persistence_manager):
        """Test statistics calculation with error."""
        test_persistence_manager.load_session_history = Mock(side_effect=Exception("Load error"))
        
        stats = test_persistence_manager.get_session_statistics(days=7)
        
        assert stats == {}
        test_persistence_manager.logger.error.assert_called()
    
    def test_cleanup_old_data_success(self, test_persistence_manager, temp_dir):
        """Test cleanup of old session data."""
        # Create sessions with mixed dates
        old_session = {
            "session_id": "old-session",
            "started_at": (datetime.now() - timedelta(days=60)).isoformat()
        }
        recent_session = {
            "session_id": "recent-session",
            "started_at": (datetime.now() - timedelta(days=5)).isoformat()
        }
        
        history_file = temp_dir / "test_session_history.json"
        with open(history_file, 'w') as f:
            json.dump([old_session, recent_session], f)
        
        test_persistence_manager.session_history_file = history_file
        
        with patch('persistence.APP_CONFIG') as mock_config:
            mock_config.session_history_retention_days = 30
            
            test_persistence_manager.cleanup_old_data()
        
        # Verify old session was removed
        with open(history_file, 'r') as f:
            saved_data = json.load(f)
        
        assert len(saved_data) == 1
        assert saved_data[0]["session_id"] == "recent-session"
        
        test_persistence_manager.logger.info.assert_called()
    
    def test_cleanup_old_data_no_cleanup_needed(self, test_persistence_manager, temp_dir):
        """Test cleanup when no cleanup is needed."""
        recent_session = {
            "session_id": "recent-session",
            "started_at": (datetime.now() - timedelta(days=5)).isoformat()
        }
        
        history_file = temp_dir / "test_session_history.json"
        with open(history_file, 'w') as f:
            json.dump([recent_session], f)
        
        test_persistence_manager.session_history_file = history_file
        
        with patch('persistence.APP_CONFIG') as mock_config:
            mock_config.session_history_retention_days = 30
            
            test_persistence_manager.cleanup_old_data()
        
        # No cleanup should have occurred
        test_persistence_manager.logger.info.assert_not_called()
    
    def test_cleanup_old_data_error(self, test_persistence_manager):
        """Test cleanup with error."""
        test_persistence_manager.load_session_history = Mock(side_effect=Exception("Load error"))
        
        test_persistence_manager.cleanup_old_data()
        
        test_persistence_manager.logger.error.assert_called_with(
            "Error during cleanup: Load error"
        )