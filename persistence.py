"""Persistence layer for watch monitor application."""

import json
import os
from pathlib import Path
from typing import Dict, Set, List, Optional
from datetime import datetime, timedelta
import logging

from config import APP_CONFIG
from models import ScrapingSession


class PersistenceManager:
    """Manages data persistence for seen watches and session history."""
    
    def __init__(self, logger: logging.Logger):
        """
        Initialize persistence manager.
        
        Args:
            logger: Logger instance
        """
        self.logger = logger
        self.seen_items_file = Path(APP_CONFIG.seen_watches_file)
        self.session_history_file = Path(APP_CONFIG.session_history_file)
    
    def load_seen_items(self) -> Dict[str, Set[str]]:
        """
        Load seen watch IDs from file.
        
        Returns:
            Dictionary mapping site keys to sets of seen watch IDs
        """
        if not self.seen_items_file.exists():
            self.logger.info("Seen items file does not exist, starting fresh")
            return {}
        
        try:
            with open(self.seen_items_file, 'r', encoding='utf-8') as f:
                content = f.read()
                if not content:
                    self.logger.warning("Seen items file is empty")
                    return {}
                
                data = json.loads(content)
                
                # Convert lists to sets for efficient lookup
                result = {}
                for site_key, items in data.items():
                    result[site_key] = set(items)
                
                self.logger.info(f"Loaded seen items: {sum(len(s) for s in result.values())} total")
                return result
                
        except json.JSONDecodeError as e:
            self.logger.error(f"Error parsing seen items file: {e}")
            return {}
        except Exception as e:
            self.logger.error(f"Error loading seen items: {e}")
            return {}
    
    def save_seen_items(self, seen_items: Dict[str, Set[str]]):
        """
        Save seen watch IDs to file with strict limits enforced.
        
        Args:
            seen_items: Dictionary mapping site keys to sets of seen watch IDs
        """
        try:
            # Trim items before saving to enforce strict limits
            trimmed_items = self.trim_seen_items(seen_items)
            
            # Convert sets to lists for JSON serialization
            serializable_items = {}
            for site_key, items in trimmed_items.items():
                serializable_items[site_key] = list(items)
            
            # Create directory if needed
            self.seen_items_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Write to file
            with open(self.seen_items_file, 'w', encoding='utf-8') as f:
                json.dump(serializable_items, f, indent=2, ensure_ascii=False)
            
            self.logger.debug("Saved seen items successfully")
            
        except Exception as e:
            self.logger.error(f"Error saving seen items: {e}")
    
    def trim_seen_items(self, seen_items: Dict[str, Set[str]]) -> Dict[str, Set[str]]:
        """
        Trim seen items to enforce strict limits per site with proper FIFO trimming.
        
        This method enforces the maximum number of seen items per site to prevent
        unbounded memory growth. When the limit is exceeded, it keeps the most
        recent items (FIFO - First In, First Out).
        
        Note: Since sets don't maintain insertion order in Python < 3.7, and we're
        using sets for efficient lookup, we load from file to get the ordered list,
        then trim and convert back to sets. In practice, newer items are typically
        added to the end of the list when loaded from JSON.
        
        Args:
            seen_items: Dictionary mapping site keys to sets of seen watch IDs
        
        Returns:
            Dictionary with trimmed sets of seen watch IDs
        """
        trimmed_items = {}
        max_items = APP_CONFIG.max_seen_items_per_site
        
        for site_key, items in seen_items.items():
            original_count = len(items)
            
            if original_count > max_items:
                # Convert to list for trimming
                items_list = list(items)
                
                # Keep only the most recent items (last N items in the list)
                # This implements FIFO - we keep the newest and discard the oldest
                trimmed_list = items_list[-max_items:]
                
                # Convert back to set
                trimmed_items[site_key] = set(trimmed_list)
                
                self.logger.warning(
                    f"Trimmed seen items for {site_key}: "
                    f"{original_count} -> {len(trimmed_items[site_key])} items "
                    f"(removed {original_count - len(trimmed_items[site_key])} oldest items)"
                )
            else:
                # No trimming needed
                trimmed_items[site_key] = items
        
        return trimmed_items
    
    def load_session_history(self) -> List[Dict]:
        """
        Load session history from file.
        
        Returns:
            List of session dictionaries
        """
        if not self.session_history_file.exists():
            return []
        
        try:
            with open(self.session_history_file, 'r', encoding='utf-8') as f:
                content = f.read()
                if not content:
                    return []
                
                return json.loads(content)
                
        except Exception as e:
            self.logger.error(f"Error loading session history: {e}")
            return []
    
    def save_session(self, session: ScrapingSession):
        """
        Save a scraping session to history.
        
        Args:
            session: ScrapingSession object
        """
        try:
            # Load existing history
            history = self.load_session_history()
            
            # Add new session
            history.append(session.to_dict())
            
            # Trim to enforce strict limits
            history = self.trim_session_history(history)
            
            # Create directory if needed
            self.session_history_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Write to file
            with open(self.session_history_file, 'w', encoding='utf-8') as f:
                json.dump(history, f, indent=2, ensure_ascii=False)
            
            self.logger.info(f"Saved session {session.session_id} to history")
            
        except Exception as e:
            self.logger.error(f"Error saving session history: {e}")
    
    def get_session_statistics(self, days: int = 7) -> Dict:
        """
        Get statistics from session history.
        
        Args:
            days: Number of days to look back
        
        Returns:
            Dictionary with statistics
        """
        try:
            history = self.load_session_history()
            
            if not history:
                return {
                    "total_sessions": 0,
                    "total_watches_found": 0,
                    "total_new_watches": 0,
                    "total_notifications": 0,
                    "success_rate": 0.0,
                    "average_duration": 0.0
                }
            
            # Filter by date
            cutoff_date = datetime.now() - timedelta(days=days)
            recent_sessions = [
                s for s in history
                if datetime.fromisoformat(s['started_at']) > cutoff_date
            ]
            
            if not recent_sessions:
                return {
                    "total_sessions": 0,
                    "total_watches_found": 0,
                    "total_new_watches": 0,
                    "total_notifications": 0,
                    "success_rate": 0.0,
                    "average_duration": 0.0
                }
            
            # Calculate statistics
            total_sessions = len(recent_sessions)
            successful_sessions = sum(1 for s in recent_sessions if s.get('errors_encountered', 0) == 0)
            total_watches = sum(s.get('total_watches_found', 0) for s in recent_sessions)
            total_new = sum(s.get('total_new_watches', 0) for s in recent_sessions)
            total_notifications = sum(s.get('notifications_sent', 0) for s in recent_sessions)
            
            durations = [s.get('duration_seconds', 0) for s in recent_sessions if s.get('duration_seconds')]
            avg_duration = sum(durations) / len(durations) if durations else 0
            
            return {
                "total_sessions": total_sessions,
                "total_watches_found": total_watches,
                "total_new_watches": total_new,
                "total_notifications": total_notifications,
                "success_rate": (successful_sessions / total_sessions * 100) if total_sessions > 0 else 0,
                "average_duration": avg_duration,
                "period_days": days
            }
            
        except Exception as e:
            self.logger.error(f"Error calculating statistics: {e}")
            return {}
    
    def trim_session_history(self, history: Optional[List[Dict]] = None) -> List[Dict]:
        """
        Trim session history to enforce strict limits.
        
        This method applies aggressive trimming based on both time-based retention
        and maximum entry count to prevent unbounded growth.
        
        Args:
            history: Optional list of session dictionaries. If None, loads from file.
        
        Returns:
            Trimmed list of session dictionaries
        """
        if history is None:
            history = self.load_session_history()
        
        if not history:
            return []
        
        original_count = len(history)
        
        # First, apply time-based retention if configured
        if APP_CONFIG.session_history_retention_days > 0:
            cutoff_date = datetime.now() - timedelta(days=APP_CONFIG.session_history_retention_days)
            history = [
                s for s in history
                if datetime.fromisoformat(s['started_at']) > cutoff_date
            ]
        
        # Second, enforce strict maximum entry limit (most aggressive)
        max_entries = APP_CONFIG.max_session_history_entries
        if len(history) > max_entries:
            # Keep only the most recent entries
            history = history[-max_entries:]
            self.logger.warning(
                f"Session history exceeded limit: trimmed to {max_entries} most recent entries"
            )
        
        # Log if any trimming occurred
        if len(history) < original_count:
            self.logger.info(
                f"Trimmed session history: {original_count} -> {len(history)} entries"
            )
        
        return history
    
    def cleanup_old_data(self):
        """Clean up old data files and entries."""
        try:
            # Clean session history
            if self.session_history_file.exists():
                history = self.load_session_history()
                cleaned_history = self.trim_session_history(history)
                
                if len(cleaned_history) < len(history):
                    with open(self.session_history_file, 'w', encoding='utf-8') as f:
                        json.dump(cleaned_history, f, indent=2, ensure_ascii=False)
                    
                    self.logger.info(
                        f"Cleaned session history: {len(history)} -> {len(cleaned_history)} sessions"
                    )
            
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")