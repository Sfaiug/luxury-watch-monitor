"""
Memory monitoring utility for tracking and managing application memory usage.

This module provides the MemoryMonitor class for monitoring memory consumption,
logging memory statistics, checking thresholds, and forcing garbage collection.
"""

import gc
import logging
from typing import Tuple

try:
    import psutil
except ImportError:
    psutil = None


class MemoryMonitor:
    """
    Utility class for monitoring and managing application memory usage.
    
    This class provides methods to:
    - Get current memory usage
    - Log memory statistics
    - Check memory thresholds
    - Force garbage collection
    """
    
    def __init__(self):
        """Initialize the MemoryMonitor."""
        if psutil is None:
            raise ImportError(
                "psutil is required for memory monitoring. "
                "Install it with: pip install psutil"
            )
        self.process = psutil.Process()
    
    def get_current_usage_mb(self) -> float:
        """
        Get the current memory usage of the process in megabytes.
        
        Returns:
            float: Current memory usage in MB (RSS - Resident Set Size)
        """
        memory_info = self.process.memory_info()
        return memory_info.rss / (1024 * 1024)  # Convert bytes to MB
    
    def log_memory_stats(self, logger: logging.Logger, context: str = "") -> None:
        """
        Log current memory statistics with optional context.
        
        Args:
            logger: Logger instance to use for logging
            context: Optional context string to include in the log message
        """
        try:
            memory_mb = self.get_current_usage_mb()
            memory_info = self.process.memory_info()
            
            # Get additional memory details
            vms_mb = memory_info.vms / (1024 * 1024)  # Virtual memory size
            
            context_str = f" [{context}]" if context else ""
            logger.info(
                f"Memory usage{context_str}: "
                f"RSS={memory_mb:.2f}MB, VMS={vms_mb:.2f}MB"
            )
            
        except Exception as e:
            logger.error(f"Failed to log memory stats: {e}")
    
    def check_memory_threshold(
        self, 
        logger: logging.Logger, 
        threshold_mb: float,
        threshold_name: str = "threshold"
    ) -> bool:
        """
        Check if current memory usage exceeds a threshold and log a warning if so.
        
        Args:
            logger: Logger instance to use for logging
            threshold_mb: Memory threshold in megabytes
            threshold_name: Name of the threshold for logging purposes
            
        Returns:
            bool: True if threshold is exceeded, False otherwise
        """
        try:
            current_mb = self.get_current_usage_mb()
            
            if current_mb > threshold_mb:
                logger.warning(
                    f"Memory usage ({current_mb:.2f}MB) exceeds "
                    f"{threshold_name} ({threshold_mb}MB)"
                )
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to check memory threshold: {e}")
            return False
    
    def force_garbage_collection(self) -> Tuple[int, int, int]:
        """
        Force Python garbage collection and return collection statistics.
        
        This method triggers garbage collection for all generations and returns
        the number of objects collected in each generation.
        
        Returns:
            Tuple[int, int, int]: Number of objects collected in each generation
                                  (generation 0, generation 1, generation 2)
        """
        # Get counts before collection
        before_counts = gc.get_count()
        
        # Force collection of all generations
        collected = []
        for generation in range(3):
            num_collected = gc.collect(generation)
            collected.append(num_collected)
        
        return tuple(collected)

    def trim_memory(self) -> bool:
        """
        Force Python to return freed memory to the operating system.

        Uses malloc_trim() on Linux to release memory from Python's memory
        allocator back to the OS. This is critical for preventing RSS growth
        because Python's pymalloc does not automatically return freed memory.

        Background:
        - Python uses reference counting + garbage collection for memory management
        - When objects are freed, memory is released to Python's internal pool
        - BUT Python does not automatically return this memory to the OS
        - RSS (Resident Set Size) stays high even with freed objects
        - malloc_trim() forces the allocator to return memory to OS

        Platform support:
        - Linux: malloc_trim() from libc.so.6 (fully supported)
        - macOS: Not available (no equivalent function)
        - Windows: Uses _heapmin() from msvcrt

        Returns:
            bool: True if malloc_trim was called successfully, False otherwise

        Requirements: 3.1, 4.1
        """
        try:
            import ctypes
            import platform

            system = platform.system()

            if system == 'Linux':
                # On Linux, use malloc_trim from glibc
                try:
                    libc = ctypes.CDLL('libc.so.6')
                    # malloc_trim(0) releases all possible memory to OS
                    # Returns 1 if memory was released, 0 otherwise
                    result = libc.malloc_trim(0)
                    return result == 1
                except (OSError, AttributeError) as e:
                    return False

            elif system == 'Darwin':  # macOS
                # macOS doesn't have malloc_trim
                # We'll rely on GC more heavily here
                return False

            elif system == 'Windows':
                # Windows uses _heapmin to compact heap
                try:
                    msvcrt = ctypes.CDLL('msvcrt')
                    result = msvcrt._heapmin()
                    return result == 0  # 0 = success
                except (OSError, AttributeError):
                    return False

            # Unknown platform
            return False

        except Exception as e:
            # If anything goes wrong, fail gracefully
            return False
