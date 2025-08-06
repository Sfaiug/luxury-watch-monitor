#!/usr/bin/env python3
"""
Watch Monitor - Luxury Watch Monitoring System

A refactored, production-ready application for monitoring luxury watch retailers
and sending Discord notifications for new listings.
"""

import asyncio
import argparse
import sys
from pathlib import Path

from monitor import WatchMonitor


async def main():
    """Main entry point for the watch monitor application."""
    parser = argparse.ArgumentParser(
        description="Monitor luxury watch retailers for new listings",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run continuous monitoring
  python main.py
  
  # Run single cycle with debug logging
  python main.py --single --log-level DEBUG
  
  # Validate configuration without running
  python main.py --validate
  
  # View statistics for last 30 days
  python main.py --stats 30
  
  # Run with file logging
  python main.py --log-file logs/watch_monitor.log
        """
    )
    
    parser.add_argument(
        "--single",
        action="store_true",
        help="Run a single monitoring cycle and exit"
    )
    
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate configuration and test connections"
    )
    
    parser.add_argument(
        "--stats",
        type=int,
        metavar="DAYS",
        help="Show statistics for the last N days and exit"
    )
    
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Set logging level (default: INFO)"
    )
    
    parser.add_argument(
        "--log-file",
        help="Path to log file (logs to console if not specified)"
    )
    
    args = parser.parse_args()
    
    # Create monitor instance
    monitor = WatchMonitor(
        log_level=args.log_level,
        log_file=args.log_file
    )
    
    try:
        # Initialize monitor
        await monitor.initialize()
        
        # Handle different modes
        if args.stats:
            # Show statistics
            stats = monitor.get_statistics(args.stats)
            
            print(f"\n📊 Watch Monitor Statistics (Last {args.stats} days)")
            print("=" * 50)
            print(f"Total Sessions:       {stats.get('total_sessions', 0)}")
            print(f"Total Watches Found:  {stats.get('total_watches_found', 0)}")
            print(f"New Watches Found:    {stats.get('total_new_watches', 0)}")
            print(f"Notifications Sent:   {stats.get('total_notifications', 0)}")
            print(f"Success Rate:         {stats.get('success_rate', 0):.1f}%")
            print(f"Avg Session Duration: {stats.get('average_duration', 0):.1f}s")
            print("=" * 50)
            
        elif args.validate:
            # Validate configuration
            print("\n🔍 Validating Configuration...")
            print("=" * 50)
            
            valid = await monitor.validate_configuration()
            
            if valid:
                print("\n✅ All validations passed!")
            else:
                print("\n❌ Some validations failed. Check the logs above.")
                sys.exit(1)
                
        elif args.single:
            # Run single cycle
            print("\n🔄 Running single monitoring cycle...")
            session = await monitor.run_monitoring_cycle()
            
            print(f"\n✅ Cycle complete!")
            print(f"   New watches found: {session.total_new_watches}")
            print(f"   Notifications sent: {session.notifications_sent}")
            
        else:
            # Run continuous monitoring
            print("\n🚀 Starting continuous monitoring...")
            print("   Press Ctrl+C to stop gracefully\n")
            
            await monitor.run_continuous()
            
    except KeyboardInterrupt:
        print("\n\n⏹️  Monitoring stopped by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        monitor.logger.exception("Unexpected error in main")
        sys.exit(1)
    finally:
        # Clean up
        await monitor.cleanup()
        print("\n👋 Goodbye!")


if __name__ == "__main__":
    # Run the async main function
    asyncio.run(main())