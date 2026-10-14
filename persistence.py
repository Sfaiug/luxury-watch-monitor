"""Persistence layer for watch monitor application."""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import logging

from config import APP_CONFIG
from models import ScrapingSession


class SeenIds(dict):
    """The ids a shop's watches are remembered under, the one seen longest ago first.

    A set that keeps its order: seeing an id again moves it to the end, so
    the ids forgotten when the memory is full are those of watches no
    longer listed, never of one still on the page.
    """

    def add(self, seen_id: str):
        self.pop(seen_id, None)
        self[seen_id] = None

    def discard(self, seen_id: str):
        self.pop(seen_id, None)

    def forget_oldest(self, keep: int) -> int:
        """Drop the ids seen longest ago beyond `keep`; how many went."""
        excess = max(len(self) - keep, 0)
        for seen_id in list(self)[:excess]:
            del self[seen_id]
        return excess


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

        self._seen_items_load_failed = False

    @property
    def _seen_items_backup_file(self) -> Path:
        return self.seen_items_file.with_name(self.seen_items_file.name + ".bak")
    
    def load_seen_items(self) -> Dict[str, SeenIds]:
        """
        Load seen watch IDs from file.
        
        Returns:
            Dictionary mapping site keys to sets of seen watch IDs
        """
        # Cleanup must not overwrite unreadable history after a failed startup.
        self._seen_items_load_failed = True
        missing = 0
        for path in (self.seen_items_file, self._seen_items_backup_file):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or any(
                    not isinstance(items, list)
                    or any(not isinstance(item, str) for item in items)
                    for items in data.values()
                ):
                    raise ValueError("Expected a mapping of sources to lists of seen IDs")
                result = {key: SeenIds.fromkeys(items) for key, items in data.items()}
            except FileNotFoundError:
                missing += 1
                continue
            except (OSError, ValueError) as e:
                self.logger.error(f"Error loading seen items from {path}: {e}")
                continue

            if path == self._seen_items_backup_file:
                self.logger.warning(f"Recovered seen items from last good state in {path}")
            self._seen_items_load_failed = False
            self.logger.info(f"Loaded seen items: {sum(len(s) for s in result.values())} total")
            return result

        if missing == 2:
            self._seen_items_load_failed = False
            self.logger.info("Seen items file does not exist, starting fresh")
            return {}

        raise RuntimeError("Cannot recover seen items; refusing to start with an empty history")
    
    def save_seen_items(self, seen_items: Dict[str, SeenIds]):
        """
        Save seen watch IDs to file, each shop's within its limit.

        Args:
            seen_items: Dictionary mapping site keys to their seen watch IDs
        """
        try:
            if self._seen_items_load_failed:
                raise RuntimeError("Refusing to overwrite seen items after failed recovery")
            self.trim_seen_items(seen_items)

            # Create directory if needed
            self.seen_items_file.parent.mkdir(parents=True, exist_ok=True)

            data = {site_key: list(items) for site_key, items in seen_items.items()}
            # Keep the same snapshot as a backup first; neither good file is
            # replaced until its new contents have been written and flushed.
            for path in (self._seen_items_backup_file, self.seen_items_file):
                beside = path.with_name(path.name + ".tmp")
                with open(beside, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                beside.replace(path)

            self.logger.debug("Saved seen items successfully")

        except Exception as e:
            self.logger.error(f"Error saving seen items: {e}")

    def trim_seen_items(
        self, seen_items: Dict[str, SeenIds], limit: Optional[int] = None
    ) -> Dict[str, SeenIds]:
        """
        Keep each shop's memory within the limit by forgetting, in place, the
        ids seen longest ago. The scraper and the monitor share that memory,
        so what is saved is what they go on with.

        Args:
            seen_items: Dictionary mapping site keys to their seen watch IDs
            limit: Ids to keep per shop; MAX_SEEN_ITEMS_PER_SITE when not given

        Returns:
            The same dictionary
        """
        if limit is None:
            limit = APP_CONFIG.max_seen_items_per_site

        for site_key, items in seen_items.items():
            forgotten = items.forget_oldest(limit)
            if forgotten:
                self.logger.warning(
                    f"Trimmed seen items for {site_key}: "
                    f"{len(items) + forgotten} -> {len(items)} items "
                    f"(removed {forgotten} oldest items)"
                )

        return seen_items

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

            # Trim to enforce strict limits BEFORE appending (prevents memory spikes)
            history = self.trim_session_history(history)

            # Add new session
            history.append(session.to_dict())
            
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