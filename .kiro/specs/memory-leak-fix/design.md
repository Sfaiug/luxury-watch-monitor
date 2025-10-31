# Design Document: Memory Leak Fix

## Overview

The watch monitor application suffers from multiple memory leaks that cause RAM usage to grow linearly over time, eventually crashing the VM after approximately one week. Analysis of the codebase reveals several critical issues:

1. **Unbounded session history growth** - The `session_history.json` file grows indefinitely with no effective limits
2. **BeautifulSoup object retention** - HTML parsing objects are not explicitly cleared after use
3. **aiohttp connection accumulation** - While connection pooling is configured, connections may not be properly released
4. **Large in-memory data structures** - Seen items sets can grow very large without bounds
5. **No memory monitoring** - The application has no visibility into its own memory usage

This design addresses each of these issues with targeted fixes and implements monitoring to prevent future regressions.

## Architecture

### Memory Management Strategy

The fix implements a multi-layered approach:

1. **Proactive Limits**: Enforce hard limits on data structure sizes before they grow too large
2. **Explicit Cleanup**: Add explicit resource cleanup at the end of each operation
3. **Periodic Maintenance**: Implement periodic cleanup tasks that run during monitoring cycles
4. **Monitoring & Alerting**: Add memory usage tracking and logging to detect issues early

### Component Changes

```
┌─────────────────────────────────────────────────────────────┐
│                     WatchMonitor                             │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  Memory Monitor (NEW)                                   │ │
│  │  - Track memory usage                                   │ │
│  │  - Log warnings at thresholds                           │ │
│  │  - Trigger garbage collection                           │ │
│  └────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  Cleanup Manager (NEW)                                  │ │
│  │  - Clear BeautifulSoup objects                          │ │
│  │  - Trim data structures                                 │ │
│  │  - Force garbage collection                             │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                  PersistenceManager                          │
│  - Enforce strict limits on session history (1000 max)      │
│  - Enforce strict limits on seen items (10k per site)       │
│  - Implement aggressive cleanup of old data                 │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                     BaseScraper                              │
│  - Explicitly clear soup objects after parsing              │
│  - Use context managers for all resources                   │
│  - Avoid storing large objects in instance variables        │
└─────────────────────────────────────────────────────────────┘
```

## Components and Interfaces

### 1. Memory Monitor (New Component)

**Purpose**: Track and report memory usage throughout the application lifecycle

**Interface**:
```python
class MemoryMonitor:
    def get_current_usage_mb() -> float
    def log_memory_stats(logger, context: str)
    def check_memory_threshold(logger, threshold_mb: int) -> bool
    def force_garbage_collection() -> tuple[int, int, int]
```

**Implementation Details**:
- Uses `psutil` library to get process memory info
- Logs memory usage after each monitoring cycle
- Triggers warnings when memory exceeds configurable thresholds
- Can force garbage collection when needed

### 2. Enhanced PersistenceManager

**Changes**:
- Reduce `session_history` retention from unlimited to strict 1000 entry limit
- Implement aggressive trimming of seen items (currently 10k limit exists but not enforced properly)
- Add periodic cleanup method that runs every N cycles
- Use streaming JSON writes for large files to avoid loading entire file into memory

**New Methods**:
```python
def trim_session_history(max_entries: int = 1000)
def trim_seen_items(max_per_site: int = 10000)
def cleanup_old_data(force: bool = False)
```

### 3. Enhanced BaseScraper

**Changes**:
- Explicitly call `soup.decompose()` after parsing to release memory
- Clear watch lists after processing
- Avoid storing parsed HTML in instance variables
- Use generators where possible instead of lists

**New Methods**:
```python
def _cleanup_soup(soup: BeautifulSoup)
def _clear_temporary_data()
```

### 4. Enhanced WatchMonitor

**Changes**:
- Add memory monitoring after each cycle
- Implement periodic cleanup (every 10 cycles)
- Force garbage collection after cleanup
- Add memory stats to session data

**New Methods**:
```python
def _perform_periodic_cleanup(cycle_count: int)
def _log_memory_stats()
```

## Data Models

### Session Model Enhancement

Add memory tracking fields to `ScrapingSession`:

```python
@dataclass
class ScrapingSession:
    # ... existing fields ...
    
    # Memory tracking (NEW)
    memory_usage_start_mb: Optional[float] = None
    memory_usage_end_mb: Optional[float] = None
    memory_delta_mb: Optional[float] = None
```

### Configuration Enhancement

Add memory-related configuration to `AppConfig`:

```python
@dataclass
class AppConfig:
    # ... existing fields ...
    
    # Memory management (NEW)
    memory_warning_threshold_mb: int = 400
    memory_critical_threshold_mb: int = 500
    force_gc_every_n_cycles: int = 10
    max_session_history_entries: int = 1000
```

## Error Handling

### Memory Threshold Exceeded

**Scenario**: Memory usage exceeds warning threshold (400MB)

**Handling**:
1. Log warning with current memory stats
2. Trigger immediate garbage collection
3. Perform emergency cleanup of old data
4. Continue operation

**Scenario**: Memory usage exceeds critical threshold (500MB)

**Handling**:
1. Log critical error
2. Force aggressive garbage collection
3. Trim all data structures to minimum
4. If still above threshold, consider graceful restart

### Cleanup Failures

**Scenario**: File cleanup operations fail

**Handling**:
1. Log error but continue operation
2. Retry on next cleanup cycle
3. Don't crash the monitoring process

### Resource Cleanup Failures

**Scenario**: aiohttp session cleanup fails

**Handling**:
1. Log error
2. Create new session on next cycle
3. Let Python garbage collector handle old session

## Testing Strategy

### Memory Leak Testing

**Approach**: Run extended tests to verify memory stability

1. **Short-term test** (1 hour):
   - Run monitor continuously for 1 hour
   - Sample memory usage every 5 minutes
   - Verify memory stays below 200MB
   - Verify no upward trend

2. **Medium-term test** (24 hours):
   - Run monitor continuously for 24 hours
   - Sample memory usage every 30 minutes
   - Verify memory stays below 300MB
   - Verify memory stabilizes (no linear growth)

3. **Long-term test** (7 days):
   - Run monitor continuously for 7 days
   - Sample memory usage every hour
   - Verify memory stays below 400MB
   - Verify no crashes

### Unit Testing

1. **Test memory monitor**:
   - Verify memory usage reporting is accurate
   - Test threshold detection
   - Test garbage collection triggering

2. **Test persistence limits**:
   - Verify session history is trimmed to 1000 entries
   - Verify seen items are trimmed to 10k per site
   - Test cleanup operations

3. **Test scraper cleanup**:
   - Verify BeautifulSoup objects are cleared
   - Test that temporary data is released
   - Verify no references are retained

### Integration Testing

1. **Test full monitoring cycle**:
   - Run complete cycle
   - Verify memory returns to baseline after cycle
   - Check that all resources are released

2. **Test periodic cleanup**:
   - Run 20 cycles
   - Verify cleanup triggers every 10 cycles
   - Verify memory is reclaimed

## Implementation Notes

### Critical Fixes (Priority 1)

1. **Fix session history growth** - This is likely the primary leak
   - Current code has retention logic but it's not aggressive enough
   - Need to enforce hard 1000 entry limit

2. **Clear BeautifulSoup objects** - Significant memory savings
   - Add `soup.decompose()` after each parse
   - Clear soup references immediately

3. **Add memory monitoring** - Essential for validation
   - Log memory after each cycle
   - Alert on thresholds

### Important Fixes (Priority 2)

4. **Periodic garbage collection** - Helps reclaim memory
   - Force GC every 10 cycles
   - Log collection stats

5. **Trim seen items more aggressively** - Prevent unbounded growth
   - Current 10k limit may be too high
   - Consider reducing to 5k

### Nice-to-Have (Priority 3)

6. **Memory profiling mode** - For debugging
   - Optional detailed memory tracking
   - Generate memory reports

7. **Graceful degradation** - Handle extreme cases
   - Disable detail scraping if memory high
   - Reduce concurrent operations

## Deployment Considerations

### Backward Compatibility

- All changes are backward compatible
- Existing data files will be automatically trimmed on first run
- No configuration changes required (all have defaults)

### Rollout Strategy

1. Deploy to test environment
2. Run 24-hour memory test
3. Monitor memory usage closely
4. Deploy to production with monitoring
5. Continue monitoring for 7 days

### Monitoring

After deployment, monitor:
- Memory usage trends (should be flat)
- Session history file size (should stabilize at ~1000 entries)
- Seen watches file size (should stabilize)
- Application logs for memory warnings

### Rollback Plan

If memory issues persist:
1. Revert to previous version
2. Implement more aggressive limits
3. Consider architectural changes (e.g., external database)
