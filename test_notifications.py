#!/usr/bin/env python3
"""
Test script for verifying Discord notifications for Watch Out and Tropical Watch scrapers.

Usage:
    python test_notifications.py                   # Test all scrapers
    python test_notifications.py watch_out         # Test only Watch Out
    python test_notifications.py tropicalwatch     # Test only Tropical Watch
    python test_notifications.py --reset-all       # Reset all seen watches and test
"""

import asyncio
import argparse
import sys
import os
from pathlib import Path
from datetime import datetime
import json

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from monitor import WatchMonitor
from config import SITE_CONFIGS, APP_CONFIG
from persistence import PersistenceManager
from logging_config import setup_logging


def check_webhooks(sites=None):
    """Check webhook configuration for specified sites."""
    sites = sites or ['watch_out', 'tropicalwatch']
    missing = []
    configured = []
    
    for site_key in sites:
        if site_key in SITE_CONFIGS:
            site_config = SITE_CONFIGS[site_key]
            if site_config.webhook_url:
                configured.append((site_key, site_config.name))
            else:
                missing.append((site_key, site_config.webhook_env_var, site_config.name))
    
    return configured, missing


def show_seen_watches_status():
    """Display current seen watches status."""
    logger = setup_logging("INFO")
    persistence = PersistenceManager(logger)
    seen_items = persistence.load_seen_items()
    
    print("\n📊 Current Seen Watches Status:")
    print("=" * 60)
    
    if not seen_items:
        print("   No seen watches recorded yet")
    else:
        total = 0
        for site_key, items in seen_items.items():
            count = len(items)
            total += count
            site_name = SITE_CONFIGS.get(site_key, {}).get('name', site_key)
            print(f"   {site_name:25} {count:5} watches")
        print("-" * 60)
        print(f"   {'TOTAL':25} {total:5} watches")
    
    print("=" * 60)
    return seen_items


async def test_single_scraper(monitor, site_key):
    """Test a single scraper and report results."""
    print(f"\n🔍 Testing {SITE_CONFIGS[site_key].name} scraper...")
    print("-" * 60)
    
    scraper = monitor.scrapers.get(site_key)
    if not scraper:
        print(f"❌ Scraper not found for {site_key}")
        return False
    
    try:
        # Run the scraper
        print(f"   Fetching {SITE_CONFIGS[site_key].url}...")
        new_watches = await scraper.scrape()
        
        # Report findings
        print(f"\n   📦 Results:")
        print(f"      Total watches found:     {len(scraper.seen_ids)}")
        print(f"      New watches detected:    {len(new_watches)}")
        
        if new_watches:
            print(f"\n   🆕 New watches to notify about:")
            for i, watch in enumerate(new_watches[:5], 1):  # Show first 5
                print(f"      {i}. {watch.title[:60]}...")
                print(f"         Price: {watch.price_display or 'N/A'}")
                print(f"         URL: {watch.url}")
                print(f"         ID: {watch.composite_id[:16]}...")
            
            if len(new_watches) > 5:
                print(f"      ... and {len(new_watches) - 5} more")
            
            # Send notifications
            if APP_CONFIG.enable_notifications and SITE_CONFIGS[site_key].webhook_url:
                print(f"\n   📨 Sending Discord notifications...")
                notifications_sent = await monitor.notification_manager.send_notifications(
                    new_watches,
                    SITE_CONFIGS[site_key]
                )
                
                if notifications_sent == len(new_watches):
                    print(f"   ✅ Successfully sent {notifications_sent} notifications!")
                else:
                    print(f"   ⚠️  Only {notifications_sent}/{len(new_watches)} notifications sent")
            else:
                if not APP_CONFIG.enable_notifications:
                    print(f"   ⚠️  Notifications are disabled in configuration")
                else:
                    print(f"   ⚠️  No webhook configured for {site_key}")
        else:
            print(f"\n   ℹ️  No new watches detected")
            print(f"      This could mean:")
            print(f"      - All watches are already in seen_watches.json")
            print(f"      - No watches found on the site")
            print(f"      - Use --reset flag to clear seen watches")
        
        # Update seen items
        monitor.seen_items[site_key] = scraper.seen_ids
        monitor.persistence.save_seen_items(monitor.seen_items)
        
        return True
        
    except Exception as e:
        print(f"❌ Error testing {site_key}: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Main test function."""
    parser = argparse.ArgumentParser(
        description="Test Discord notifications for watch scrapers",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        "sites",
        nargs="*",
        choices=["watch_out", "tropicalwatch", "all"],
        default=["all"],
        help="Sites to test (default: all)"
    )
    
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset seen watches before testing"
    )
    
    parser.add_argument(
        "--reset-all",
        action="store_true",
        help="Reset ALL seen watches (not just test sites)"
    )
    
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Test without sending actual notifications"
    )
    
    args = parser.parse_args()
    
    # Determine which sites to test
    test_sites = []
    if "all" in args.sites or not args.sites:
        test_sites = ["watch_out", "tropicalwatch"]
    else:
        test_sites = args.sites
    
    print("\n🧪 Watch Monitor Notification Test")
    print("=" * 60)
    print(f"   Testing sites: {', '.join(test_sites)}")
    print(f"   Reset mode:    {'Yes' if args.reset or args.reset_all else 'No'}")
    print(f"   Debug mode:    {'Yes' if args.debug else 'No'}")
    print(f"   Dry run:       {'Yes' if args.dry_run else 'No'}")
    print("=" * 60)
    
    # Check webhook configuration
    configured, missing = check_webhooks(test_sites)
    
    if configured:
        print("\n✅ Configured webhooks:")
        for site_key, site_name in configured:
            print(f"   - {site_name}")
    
    if missing:
        print("\n⚠️  Missing webhook configuration:")
        for site_key, env_var, site_name in missing:
            print(f"   - {site_name}: Set {env_var} environment variable")
        print("\n💡 Tip: Create a .env file with webhook URLs")
        
        if not args.dry_run:
            response = input("\nContinue anyway? (y/N): ")
            if response.lower() != 'y':
                print("Aborted.")
                return
    
    # Show current status
    seen_items = show_seen_watches_status()
    
    # Handle reset
    if args.reset or args.reset_all:
        print("\n🔄 Resetting seen watches...")
        logger = setup_logging("INFO")
        persistence = PersistenceManager(logger)
        
        if args.reset_all:
            # Reset all
            persistence.save_seen_items({})
            print("   ✅ Reset ALL seen watches")
        else:
            # Reset only test sites
            for site_key in test_sites:
                if site_key in seen_items:
                    del seen_items[site_key]
                    print(f"   ✅ Reset {SITE_CONFIGS[site_key].name}")
            persistence.save_seen_items(seen_items)
    
    # Disable notifications for dry run
    if args.dry_run:
        APP_CONFIG.enable_notifications = False
    
    # Create monitor
    log_level = "DEBUG" if args.debug else "INFO"
    monitor = WatchMonitor(log_level=log_level)
    
    try:
        # Initialize
        print("\n🚀 Initializing monitor...")
        await monitor.initialize()
        
        # Test each site
        results = {}
        for site_key in test_sites:
            success = await test_single_scraper(monitor, site_key)
            results[site_key] = success
        
        # Summary
        print("\n" + "=" * 60)
        print("📊 TEST SUMMARY")
        print("=" * 60)
        
        for site_key, success in results.items():
            status = "✅ PASS" if success else "❌ FAIL"
            print(f"   {SITE_CONFIGS[site_key].name:25} {status}")
        
        all_passed = all(results.values())
        
        if all_passed:
            print("\n✅ All tests passed! Check Discord for notifications.")
        else:
            print("\n❌ Some tests failed. Check the logs above for details.")
        
        print("=" * 60)
        
        return 0 if all_passed else 1
        
    finally:
        await monitor.cleanup()


if __name__ == "__main__":
    # Load .env if exists
    if Path(".env").exists():
        try:
            from dotenv import load_dotenv
            load_dotenv()
            print("✅ Loaded configuration from .env file")
        except ImportError:
            print("⚠️  python-dotenv not installed, using system environment variables")
    
    # Run
    exit_code = asyncio.run(main())
    sys.exit(exit_code)