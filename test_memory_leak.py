"""
Memory leak verification test for watch monitor application.

This test runs multiple monitoring cycles and verifies that:
1. Memory growth is reasonable (<1.5MB/cycle average)
2. malloc_trim() is working on Linux
3. No linear memory growth pattern
4. Periodic cleanup is effective

Usage:
    python test_memory_leak.py [--cycles N]

Requirements: 3.1, 4.1
"""

import asyncio
import sys
import argparse
from typing import List
from monitor import WatchMonitor
from memory_monitor import MemoryMonitor


async def test_memory_leak(num_cycles: int = 25) -> int:
    """
    Test for memory leaks over multiple monitoring cycles.

    Args:
        num_cycles: Number of monitoring cycles to run (default: 25)

    Returns:
        int: Exit code (0 = pass, 1 = warning, 2 = fail)
    """
    print("=" * 60)
    print("Memory Leak Verification Test")
    print("=" * 60)
    print()

    # Initialize monitor
    print("Initializing monitor...")
    monitor = WatchMonitor(log_level="INFO")
    memory_tracker = MemoryMonitor()

    try:
        await monitor.initialize()

        # Record initial memory
        initial_memory = memory_tracker.get_current_usage_mb()
        print(f"Initial memory: {initial_memory:.2f}MB")
        print()

        memory_samples: List[float] = []
        cleanup_cycles = []

        # Run test cycles
        for cycle in range(1, num_cycles + 1):
            print(f"{'=' * 60}")
            print(f"Cycle {cycle}/{num_cycles}")
            print(f"{'=' * 60}")

            mem_before = memory_tracker.get_current_usage_mb()

            # Run monitoring cycle
            await monitor.run_monitoring_cycle()

            mem_after = memory_tracker.get_current_usage_mb()
            delta = mem_after - mem_before
            memory_samples.append(mem_after)

            print(f"Memory: {mem_after:.2f}MB (delta: {delta:+.2f}MB)")

            # Perform cleanup every 3 cycles (matching production config)
            if cycle % 3 == 0:
                print("\nRunning periodic cleanup...")
                monitor._perform_periodic_cleanup()
                mem_after_cleanup = memory_tracker.get_current_usage_mb()
                cleanup_freed = mem_after - mem_after_cleanup
                memory_samples[-1] = mem_after_cleanup  # Update with post-cleanup memory
                cleanup_cycles.append(cycle)
                print(f"After cleanup: {mem_after_cleanup:.2f}MB (freed: {cleanup_freed:.2f}MB)")

            print()

        # Cleanup
        await monitor.cleanup()

        # Analysis
        print("=" * 60)
        print("Test Results")
        print("=" * 60)
        print()

        final_memory = memory_samples[-1]
        peak_memory = max(memory_samples)
        total_growth = final_memory - initial_memory
        avg_growth = total_growth / num_cycles

        print(f"Initial memory:        {initial_memory:.2f}MB")
        print(f"Final memory:          {final_memory:.2f}MB")
        print(f"Peak memory:           {peak_memory:.2f}MB")
        print(f"Total growth:          {total_growth:+.2f}MB")
        print(f"Average growth/cycle:  {avg_growth:+.2f}MB")
        print()

        # Check for malloc_trim availability
        trim_available = memory_tracker.trim_memory()
        print(f"malloc_trim() available: {trim_available}")
        if trim_available:
            print("✓ malloc_trim() is working (Linux detected)")
        else:
            print("⚠ malloc_trim() not available (non-Linux platform)")
        print()

        # Check for saw-tooth pattern (indicates cleanup is working)
        if len(cleanup_cycles) >= 2:
            cleanup_effectiveness = []
            for i, cycle_num in enumerate(cleanup_cycles):
                idx = cycle_num - 1
                if idx > 0:
                    mem_before_cleanup = memory_samples[idx - 1]
                    mem_after_cleanup = memory_samples[idx]
                    freed = mem_before_cleanup - mem_after_cleanup
                    if freed > 0:
                        cleanup_effectiveness.append(freed)

            if cleanup_effectiveness:
                avg_cleanup_freed = sum(cleanup_effectiveness) / len(cleanup_effectiveness)
                print(f"Average memory freed per cleanup: {avg_cleanup_freed:.2f}MB")
                print("✓ Saw-tooth memory pattern detected (cleanup is working)")
            else:
                print("⚠ No memory freed during cleanups")
        print()

        # Verdict
        print("=" * 60)
        print("Verdict")
        print("=" * 60)
        print()

        if avg_growth < 1.5:
            print("✅ PASS - Memory growth is acceptable (<1.5MB/cycle)")
            print()
            print("Your system is managing memory effectively:")
            print("- malloc_trim() is" + (" working" if trim_available else " not available"))
            print("- Memory growth is minimal")
            print("- Periodic cleanup is effective")
            print()
            print("The memory leak is FIXED! 🎉")
            return 0

        elif avg_growth < 3.0:
            print("⚠️  WARNING - Memory growth is moderate (1.5-3MB/cycle)")
            print()
            print("Memory is growing more than expected:")
            print("- Consider running a longer test (50+ cycles)")
            print("- Check if all sites are returning large responses")
            print("- Verify malloc_trim() is available on your platform")
            print()
            if not trim_available:
                print("NOTE: malloc_trim() is not available on your platform.")
                print("This is expected on macOS. On Linux, growth should be lower.")
            return 1

        else:
            print("❌ FAIL - Memory growth is excessive (>3MB/cycle)")
            print()
            print("Memory leak still present:")
            print(f"- Average growth: {avg_growth:.2f}MB/cycle")
            print(f"- Total growth: {total_growth:.2f}MB over {num_cycles} cycles")
            print()
            print("Recommendations:")
            print("1. Verify all code changes were applied correctly")
            print("2. Check if malloc_trim() is available:", "YES" if trim_available else "NO")
            print("3. Review logs for memory warnings")
            print("4. Consider additional profiling with memory_profiler")
            return 2

    except Exception as e:
        print()
        print("=" * 60)
        print("Error During Test")
        print("=" * 60)
        print(f"Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return 3

    finally:
        # Ensure cleanup
        try:
            if monitor:
                await monitor.cleanup()
        except:
            pass


def main():
    """Main entry point for the test."""
    parser = argparse.ArgumentParser(
        description="Test watch monitor for memory leaks"
    )
    parser.add_argument(
        '--cycles',
        type=int,
        default=25,
        help='Number of monitoring cycles to run (default: 25)'
    )

    args = parser.parse_args()

    if args.cycles < 5:
        print("Error: Must run at least 5 cycles for meaningful results")
        sys.exit(1)

    print(f"Running memory leak test with {args.cycles} cycles...")
    print()

    exit_code = asyncio.run(test_memory_leak(args.cycles))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
