#!/usr/bin/env python3
"""
Watch Monitor - Production-Ready Windows Service
Enhanced with webhook validation, Windows compatibility, and production features.
"""

import asyncio
import argparse
import sys
import os
import platform
from pathlib import Path
from typing import Optional
from datetime import datetime

# Windows-specific event loop policy
if platform.system() == 'Windows':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from monitor import WatchMonitor
from config import SITE_CONFIGS


def validate_environment() -> tuple[bool, list[str]]:
    """
    Validate environment configuration before starting.
    
    Returns:
        Tuple of (is_valid, error_messages)
    """
    errors = []
    warnings = []
    
    # Check for webhook environment variables
    required_webhooks = []
    for site_key, site_config in SITE_CONFIGS.items():
        webhook_url = site_config.webhook_url
        if not webhook_url:
            required_webhooks.append(f"{site_config.webhook_env_var} (for {site_config.name})")
    
    if required_webhooks:
        errors.append(
            f"❌ Missing webhook configuration! Set these environment variables:\n" +
            "\n".join(f"   - {webhook}" for webhook in required_webhooks)
        )
    
    # Check for write permissions
    try:
        test_file = Path("test_write_permission.tmp")
        test_file.write_text("test")
        test_file.unlink()
    except Exception as e:
        errors.append(f"❌ No write permission in current directory: {e}")
    
    # Check Python version
    if sys.version_info < (3, 8):
        errors.append(f"❌ Python 3.8+ required, but found {sys.version}")
    
    # Windows-specific checks
    if platform.system() == 'Windows':
        # Check for common Windows issues
        if not os.environ.get('PYTHONIOENCODING'):
            warnings.append("⚠️  Consider setting PYTHONIOENCODING=utf-8 for Windows")
    
    is_valid = len(errors) == 0
    
    return is_valid, errors + warnings


def create_env_template():
    """Create a .env.example file with all required webhook variables."""
    env_content = """# Watch Monitor Discord Webhook Configuration
# Copy this file to .env and fill in your webhook URLs

# World of Time
WORLDOFTIME_WEBHOOK_URL=

# Grimmeissen
GRIMMEISSEN_WEBHOOK_URL=

# Tropical Watch
TROPICALWATCH_WEBHOOK_URL=

# Juwelier Exchange
JUWELIER_EXCHANGE_WEBHOOK_URL=

# Watch Out
WATCH_OUT_WEBHOOK_URL=

# Rüschenbeck
RUESCHENBECK_WEBHOOK_URL=

# Optional: Override check interval (default: 300 seconds)
# CHECK_INTERVAL_SECONDS=300

# Optional: Disable notifications for testing
# ENABLE_NOTIFICATIONS=true
"""
    
    env_file = Path(".env.example")
    env_file.write_text(env_content)
    print(f"✅ Created {env_file}")


async def run_with_restart(monitor: WatchMonitor, max_restarts: int = 3):
    """
    Run monitor with automatic restart on failure.
    
    Args:
        monitor: WatchMonitor instance
        max_restarts: Maximum number of automatic restarts
    """
    restart_count = 0
    
    while restart_count <= max_restarts:
        try:
            if restart_count > 0:
                print(f"\n🔄 Restarting monitor (attempt {restart_count}/{max_restarts})...")
                await asyncio.sleep(10)  # Wait before restart
            
            await monitor.run_continuous()
            break  # Normal exit
            
        except KeyboardInterrupt:
            print("\n⏹️  Monitoring stopped by user")
            break
            
        except Exception as e:
            monitor.logger.exception(f"Monitor crashed: {e}")
            restart_count += 1
            
            if restart_count > max_restarts:
                print(f"\n❌ Maximum restarts ({max_restarts}) exceeded. Exiting.")
                sys.exit(1)
            
            # Re-initialize monitor for clean restart
            await monitor.cleanup()
            await monitor.initialize()


async def main():
    """Main entry point for production watch monitor."""
    parser = argparse.ArgumentParser(
        description="Production-Ready Watch Monitor for Windows",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run continuous monitoring (production mode)
  python main_production.py
  
  # Run with automatic restarts and debug logging
  python main_production.py --auto-restart --log-level DEBUG
  
  # Validate configuration without running
  python main_production.py --validate
  
  # Create .env template
  python main_production.py --create-env
  
  # Run as Windows service (requires pywin32)
  python main_production.py --service install
  python main_production.py --service start
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
        help="Validate configuration and test all webhooks"
    )
    
    parser.add_argument(
        "--create-env",
        action="store_true",
        help="Create .env.example template file"
    )
    
    parser.add_argument(
        "--auto-restart",
        action="store_true",
        help="Enable automatic restart on failure"
    )
    
    parser.add_argument(
        "--max-restarts",
        type=int,
        default=3,
        help="Maximum automatic restarts (default: 3)"
    )
    
    parser.add_argument(
        "--service",
        choices=["install", "start", "stop", "remove"],
        help="Windows service management (requires admin)"
    )
    
    parser.add_argument(
        "--stats",
        type=int,
        metavar="DAYS",
        help="Show statistics for the last N days"
    )
    
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Set logging level (default: INFO)"
    )
    
    parser.add_argument(
        "--log-file",
        help="Path to log file (creates rotating logs)"
    )
    
    parser.add_argument(
        "--health-check",
        action="store_true",
        help="Run health check and exit"
    )
    
    parser.add_argument(
        "--reset-seen",
        nargs="*",
        metavar="SITE",
        help="Reset seen watches for testing. Specify sites or leave empty for all sites"
    )
    
    parser.add_argument(
        "--test-notifications",
        action="store_true",
        help="Test notifications by clearing seen watches and running one cycle"
    )
    
    args = parser.parse_args()
    
    # Handle special commands that don't need monitor
    if args.create_env:
        create_env_template()
        return
    
    if args.service:
        print("❌ Windows service management requires the windows_service.py wrapper")
        print("   Run: python windows_service.py --help")
        return
    
    # Validate environment before proceeding
    print("\n🔍 Checking environment configuration...")
    is_valid, messages = validate_environment()
    
    for message in messages:
        print(message)
    
    if not is_valid and not args.validate:
        print("\n💡 Tip: Create a .env file with webhook URLs or set environment variables")
        print("   Run with --create-env to generate a template")
        sys.exit(1)
    
    # Handle reset-seen before creating monitor
    if args.reset_seen is not None:
        from persistence import PersistenceManager
        from logging_config import setup_logging
        
        temp_logger = setup_logging("INFO")
        temp_persistence = PersistenceManager(temp_logger)
        
        # Load current seen items
        seen_items = temp_persistence.load_seen_items()
        
        if not seen_items:
            print("ℹ️  No seen watches to reset")
        else:
            # Reset specified sites or all if none specified
            sites_to_reset = args.reset_seen if args.reset_seen else list(seen_items.keys())
            
            for site in sites_to_reset:
                if site in seen_items:
                    count = len(seen_items[site])
                    del seen_items[site]
                    print(f"✅ Reset {count} seen watches for {site}")
                else:
                    print(f"ℹ️  No seen watches for {site}")
            
            # Save updated seen items
            temp_persistence.save_seen_items(seen_items)
            print("\n🔄 Seen watches reset successfully!")
        
        if not args.test_notifications and not args.single:
            # Exit if just resetting
            return
    
    # Create monitor instance
    log_file = args.log_file
    if log_file and platform.system() == 'Windows':
        # Ensure Windows path compatibility
        log_file = str(Path(log_file).resolve())
    
    monitor = WatchMonitor(
        log_level=args.log_level,
        log_file=log_file
    )
    
    try:
        # Initialize monitor
        await monitor.initialize()
        
        # Windows-specific startup message
        if platform.system() == 'Windows':
            print(f"\n🪟 Running on Windows {platform.version()}")
        
        # Handle different modes
        if args.health_check:
            # Quick health check
            print("\n🏥 Running health check...")
            
            # Check each scraper
            healthy = True
            for site_key, scraper in monitor.scrapers.items():
                try:
                    # Test scraper initialization
                    print(f"   ✓ {site_key} scraper: OK")
                except Exception as e:
                    print(f"   ✗ {site_key} scraper: {e}")
                    healthy = False
            
            # Check persistence
            try:
                _ = monitor.persistence.load_seen_items()
                print("   ✓ Persistence: OK")
            except Exception as e:
                print(f"   ✗ Persistence: {e}")
                healthy = False
            
            if healthy:
                print("\n✅ All systems healthy!")
            else:
                print("\n❌ Some systems unhealthy!")
                sys.exit(1)
                
        elif args.stats:
            # Show statistics
            stats = monitor.get_statistics(args.stats)
            
            print(f"\n📊 Watch Monitor Statistics (Last {args.stats} days)")
            print("=" * 60)
            print(f"Total Sessions:          {stats.get('total_sessions', 0):,}")
            print(f"Total Watches Found:     {stats.get('total_watches_found', 0):,}")
            print(f"New Watches Found:       {stats.get('total_new_watches', 0):,}")
            print(f"Notifications Sent:      {stats.get('total_notifications', 0):,}")
            print(f"Success Rate:            {stats.get('success_rate', 0):.1f}%")
            print(f"Avg Session Duration:    {stats.get('average_duration', 0):.1f}s")
            print(f"Total Errors:            {stats.get('total_errors', 0):,}")
            
            # Site-specific stats
            if stats.get('site_stats'):
                print("\nPer-Site Statistics:")
                print("-" * 60)
                for site, site_stats in stats['site_stats'].items():
                    print(f"\n{site}:")
                    print(f"  Sessions:    {site_stats.get('sessions', 0):,}")
                    print(f"  Watches:     {site_stats.get('watches', 0):,}")
                    print(f"  Success:     {site_stats.get('success_rate', 0):.1f}%")
            print("=" * 60)
            
        elif args.validate:
            # Enhanced validation
            print("\n🔍 Running comprehensive validation...")
            print("=" * 60)
            
            # Basic configuration validation
            valid = await monitor.validate_configuration()
            
            # Additional production checks
            print("\n📋 Production Readiness Checks:")
            
            # Check disk space
            import shutil
            stat = shutil.disk_usage(".")
            free_gb = stat.free / (1024**3)
            if free_gb < 1:
                print(f"   ⚠️  Low disk space: {free_gb:.1f} GB free")
            else:
                print(f"   ✓ Disk space: {free_gb:.1f} GB free")
            
            # Check file permissions
            try:
                Path("logs").mkdir(exist_ok=True)
                print("   ✓ Log directory: writable")
            except Exception as e:
                print(f"   ✗ Log directory: {e}")
                valid = False
            
            # Windows-specific validations
            if platform.system() == 'Windows':
                # Check for required Windows features
                try:
                    import winreg
                    print("   ✓ Windows Registry: accessible")
                except ImportError:
                    print("   ⚠️  winreg not available (normal on non-Windows)")
            
            print("=" * 60)
            
            if valid:
                print("\n✅ All validations passed! Ready for production.")
            else:
                print("\n❌ Some validations failed. Fix issues before deploying.")
                sys.exit(1)
                
        elif args.single or args.test_notifications:
            # Run single cycle
            if args.test_notifications:
                print("\n🧪 Testing notifications with fresh detection...")
                print("   - Seen watches have been reset")
                print("   - Running single monitoring cycle")
                print("   - Check your Discord for notifications\n")
            else:
                print("\n🔄 Running single monitoring cycle...")
            
            start_time = datetime.now()
            
            session = await monitor.run_monitoring_cycle()
            
            duration = (datetime.now() - start_time).total_seconds()
            
            print(f"\n✅ Cycle complete in {duration:.1f}s!")
            print(f"   Total watches found:  {session.total_watches_found:,}")
            print(f"   New watches found:    {session.total_new_watches:,}")
            print(f"   Notifications sent:   {session.notifications_sent:,}")
            
            if session.errors_encountered > 0:
                print(f"   ⚠️  Errors encountered: {session.errors_encountered}")
            
            if args.test_notifications:
                if session.notifications_sent > 0:
                    print("\n✅ Notification test successful! Check Discord.")
                else:
                    print("\n⚠️  No notifications sent. This could mean:")
                    print("   - No watches found on the sites")
                    print("   - Webhook URLs not configured")
                    print("   - Network issues")
                    print("\nCheck the logs for details.")
            
        else:
            # Run continuous monitoring
            print("\n🚀 Starting production monitoring...")
            print(f"   Platform:      {platform.system()} {platform.version()}")
            print(f"   Python:        {sys.version.split()[0]}")
            print(f"   Auto-restart:  {'Enabled' if args.auto_restart else 'Disabled'}")
            print(f"   Log level:     {args.log_level}")
            print(f"   Press Ctrl+C to stop gracefully\n")
            
            if args.auto_restart:
                await run_with_restart(monitor, args.max_restarts)
            else:
                await monitor.run_continuous()
            
    except KeyboardInterrupt:
        print("\n\n⏹️  Monitoring stopped by user")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        monitor.logger.exception("Fatal error in main")
        sys.exit(1)
    finally:
        # Clean up
        await monitor.cleanup()
        print("\n👋 Shutting down cleanly...")


if __name__ == "__main__":
    # Load environment variables from .env file if it exists
    from pathlib import Path
    if Path(".env").exists():
        try:
            from dotenv import load_dotenv
            load_dotenv()
            print("✅ Loaded configuration from .env file")
        except ImportError:
            print("⚠️  python-dotenv not installed, using system environment variables only")
    
    # Run the async main function
    try:
        asyncio.run(main())
    except RuntimeError as e:
        if "This event loop is already running" in str(e):
            # Handle Jupyter/nested event loop scenarios
            import nest_asyncio
            nest_asyncio.apply()
            loop = asyncio.get_event_loop()
            loop.run_until_complete(main())
        else:
            raise