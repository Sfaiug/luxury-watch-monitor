# Implementation Plan

- [x] 1. Create memory monitoring utility module
  - Create new file `memory_monitor.py` with MemoryMonitor class
  - Implement `get_current_usage_mb()` method using psutil
  - Implement `log_memory_stats()` method for logging memory information
  - Implement `check_memory_threshold()` method for threshold detection
  - Implement `force_garbage_collection()` method to trigger Python GC
  - _Requirements: 3.2, 3.3_

- [x] 2. Update configuration with memory management settings
  - Add memory threshold configuration fields to AppConfig in `config.py`
  - Add `memory_warning_threshold_mb` (default 400)
  - Add `memory_critical_threshold_mb` (default 500)
  - Add `force_gc_every_n_cycles` (default 10)
  - Add `max_session_history_entries` (default 1000)
  - _Requirements: 1.3, 2.1_

- [x] 3. Fix session history unbounded growth in PersistenceManager
  - Modify `save_session()` method in `persistence.py` to enforce strict 1000 entry limit
  - Change session history trimming logic to be more aggressive
  - Implement `trim_session_history()` method for explicit trimming
  - Add logging when trimming occurs
  - _Requirements: 1.3, 2.1_

- [x] 4. Fix seen items unbounded growth in PersistenceManager
  - Modify `save_seen_items()` method in `persistence.py` to enforce stricter limits
  - Reduce max items per site from 10,000 to 5,000 for better memory management
  - Implement proper FIFO trimming (keep most recent items)
  - Add `trim_seen_items()` method for explicit trimming
  - _Requirements: 1.3, 2.2_

- [x] 5. Add explicit BeautifulSoup cleanup in BaseScraper
  - Add `_cleanup_soup()` method to `scrapers/base.py`
  - Call `soup.decompose()` after parsing in `scrape()` method
  - Clear soup references explicitly after use
  - Add cleanup in `_fetch_single_watch_detail()` method
  - _Requirements: 1.5, 2.4_

- [x] 6. Implement periodic cleanup in WatchMonitor
  - Add cycle counter to WatchMonitor class in `monitor.py`
  - Implement `_perform_periodic_cleanup()` method
  - Call cleanup every 10 cycles (configurable)
  - Force garbage collection during cleanup
  - Trim session history and seen items during cleanup
  - _Requirements: 1.2, 2.5, 4.1_

- [x] 7. Add memory monitoring to monitoring cycle
  - Import MemoryMonitor in `monitor.py`
  - Log memory usage at start of each monitoring cycle
  - Log memory usage at end of each monitoring cycle
  - Check memory thresholds and log warnings
  - Add memory stats to ScrapingSession model
  - _Requirements: 3.1, 3.2, 3.3_

- [x] 8. Enhance ScrapingSession model with memory tracking
  - Add `memory_usage_start_mb` field to ScrapingSession in `models.py`
  - Add `memory_usage_end_mb` field to ScrapingSession
  - Add `memory_delta_mb` field to ScrapingSession
  - Update `to_dict()` method to include memory fields
  - _Requirements: 3.3_

- [x] 9. Add explicit resource cleanup in WatchMonitor
  - Ensure aiohttp session is properly closed in `cleanup()` method
  - Add try-finally blocks for critical cleanup operations
  - Clear scrapers dictionary after cleanup
  - Clear seen_items dictionary references
  - _Requirements: 1.2, 2.3, 4.1, 4.2_

- [x] 10. Add emergency cleanup for critical memory threshold
  - Implement `_emergency_cleanup()` method in `monitor.py`
  - Trigger when memory exceeds critical threshold (500MB)
  - Perform aggressive trimming of all data structures
  - Force multiple garbage collection passes
  - Log critical warnings
  - _Requirements: 3.1, 4.1_

- [ ] 11. Add memory profiling capability
  - Add optional memory profiling mode to configuration
  - Implement detailed memory tracking using tracemalloc
  - Generate memory reports when profiling is enabled
  - Add command-line flag for memory profiling
  - _Requirements: 3.4_

- [ ] 12. Update documentation with memory management information
  - Document memory thresholds in README.md
  - Add troubleshooting section for memory issues
  - Document configuration options for memory management
  - Add monitoring recommendations
  - _Requirements: 3.2_
