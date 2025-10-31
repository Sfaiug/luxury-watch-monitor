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
