#!/usr/bin/env python3
"""
Windows Service Wrapper for Watch Monitor Application
Provides Windows service functionality with proper error handling and logging.

Requirements:
- pywin32 (installed via: pip install pywin32)
- Run as administrator for service operations
- Python 3.8+ on Windows Server 2016+ or Windows 10+

Usage:
    # Install service (run as administrator)
    python windows_service.py install

    # Start service
    python windows_service.py start

    # Stop service
    python windows_service.py stop

    # Remove service
    python windows_service.py remove

    # Debug mode (run interactively)
    python windows_service.py debug
"""

import sys
import os
import asyncio
import logging
import threading
import time
import traceback
from pathlib import Path
from typing import Optional

# Windows service imports
try:
    import win32serviceutil
    import win32service
    import win32event
    import win32api
    import win32evtlogutil
    import servicemanager
    import winerror
except ImportError as e:
    print(f"❌ Windows service dependencies not found: {e}")
    print("💡 Install with: pip install pywin32")
    print("   Then run: python -m win32api.install")
    sys.exit(1)

# Application imports
try:
    from main_production import main as production_main, validate_environment
    from monitor import WatchMonitor
except ImportError as e:
    print(f"❌ Application modules not found: {e}")
    print("💡 Make sure you're running from the correct directory")
    sys.exit(1)


class WatchMonitorService(win32serviceutil.ServiceFramework):
    """
    Windows Service wrapper for the Watch Monitor application.
    
    This service provides:
    - Auto-start on Windows boot
    - Graceful shutdown handling
    - Automatic restart on failure
    - Windows Event Log integration
    - Virtual environment support
    """
    
    # Service configuration
    _svc_name_ = "WatchMonitorService"
    _svc_display_name_ = "Watch Monitor Service"
    _svc_description_ = "Monitors watch prices and sends Discord notifications"
    _svc_deps_ = ["EventLog"]  # Depend on Event Log service
    
    # Service behavior
    _exe_name_ = sys.executable  # Use current Python interpreter
    _exe_args_ = f'"{__file__}"'
    
    def __init__(self, args):
        """Initialize the service."""
        win32serviceutil.ServiceFramework.__init__(self, args)
        
        # Event to signal service stop
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        
        # Service state
        self.is_running = False
        self.monitor_thread = None
        self.event_loop = None
        self.monitor_instance = None
        
        # Setup logging
        self.setup_logging()
        
        # Service restart configuration
        self.max_restart_attempts = 3
        self.restart_delay_seconds = 30
        self.current_restart_count = 0
        
        self.log_info("Watch Monitor Service initialized")

    def setup_logging(self):
        """Configure logging for the service."""
        try:
            # Create logs directory
            log_dir = Path("logs")
            log_dir.mkdir(exist_ok=True)
            
            # Setup file logging
            log_file = log_dir / "windows_service.log"
            
            logging.basicConfig(
                level=logging.INFO,
                format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                handlers=[
                    logging.FileHandler(log_file, encoding='utf-8'),
                    logging.StreamHandler()  # For debug mode
                ]
            )
            
            self.logger = logging.getLogger(self._svc_name_)
            
        except Exception as e:
            # Fallback to basic logging if file setup fails
            logging.basicConfig(level=logging.INFO)
            self.logger = logging.getLogger(self._svc_name_)
            self.logger.error(f"Failed to setup file logging: {e}")

    def log_info(self, message: str):
        """Log info message to both file and Windows Event Log."""
        self.logger.info(message)
        try:
            servicemanager.LogInfoMsg(f"{self._svc_name_}: {message}")
        except Exception:
            pass  # Ignore event log errors

    def log_error(self, message: str):
        """Log error message to both file and Windows Event Log."""
        self.logger.error(message)
        try:
            servicemanager.LogErrorMsg(f"{self._svc_name_}: {message}")
        except Exception:
            pass

    def log_warning(self, message: str):
        """Log warning message to both file and Windows Event Log."""
        self.logger.warning(message)
        try:
            servicemanager.LogWarningMsg(f"{self._svc_name_}: {message}")
        except Exception:
            pass

    def SvcStop(self):
        """Called when the service is asked to stop."""
        self.log_info("Service stop requested")
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        
        # Signal stop event
        win32event.SetEvent(self.stop_event)
        
        # Stop the monitoring gracefully
        self.is_running = False
        
        if self.event_loop and not self.event_loop.is_closed():
            try:
                # Schedule shutdown in the event loop
                asyncio.run_coroutine_threadsafe(
                    self.shutdown_monitor(), 
                    self.event_loop
                )
            except Exception as e:
                self.log_error(f"Error during graceful shutdown: {e}")
        
        self.log_info("Service stopped")

    def SvcDoRun(self):
        """Called when the service is asked to start."""
        try:
            self.log_info("Service starting...")
            self.ReportServiceStatus(win32service.SERVICE_START_PENDING)
            
            # Validate environment before starting
            self.log_info("Validating environment configuration")
            is_valid, messages = validate_environment()
            
            if not is_valid:
                error_msg = "Environment validation failed:\n" + "\n".join(messages)
                self.log_error(error_msg)
                self.ReportServiceStatus(win32service.SERVICE_STOPPED)
                return
            
            # Log any warnings
            for message in messages:
                if "⚠️" in message:
                    self.log_warning(message)
            
            self.log_info("Environment validation passed")
            self.ReportServiceStatus(win32service.SERVICE_RUNNING)
            
            # Start the main service loop
            self.run_service()
            
        except Exception as e:
            error_msg = f"Service startup failed: {e}\n{traceback.format_exc()}"
            self.log_error(error_msg)
            self.ReportServiceStatus(win32service.SERVICE_STOPPED)

    def run_service(self):
        """Main service execution loop with restart capability."""
        while self.is_running:
            try:
                self.log_info(f"Starting monitor (attempt {self.current_restart_count + 1})")
                
                # Reset restart count on successful start
                if self.current_restart_count > 0:
                    self.log_info("Monitor restarted successfully, resetting restart counter")
                    self.current_restart_count = 0
                
                # Run the monitoring in a separate thread to avoid blocking service operations
                self.monitor_thread = threading.Thread(
                    target=self.run_monitor_thread,
                    daemon=True
                )
                self.monitor_thread.start()
                
                # Wait for stop event or monitor thread completion
                while self.is_running:
                    # Check if service stop was requested
                    if win32event.WaitForSingleObject(self.stop_event, 1000) == win32event.WAIT_OBJECT_0:
                        self.log_info("Stop event received")
                        break
                    
                    # Check if monitor thread died unexpectedly
                    if not self.monitor_thread.is_alive():
                        self.log_warning("Monitor thread died unexpectedly")
                        break
                    
                break  # Normal exit
                
            except Exception as e:
                self.current_restart_count += 1
                error_msg = f"Monitor crashed (attempt {self.current_restart_count}): {e}\n{traceback.format_exc()}"
                self.log_error(error_msg)
                
                if self.current_restart_count >= self.max_restart_attempts:
                    self.log_error(f"Maximum restart attempts ({self.max_restart_attempts}) exceeded, stopping service")
                    break
                
                # Wait before restarting
                self.log_info(f"Waiting {self.restart_delay_seconds} seconds before restart")
                time.sleep(self.restart_delay_seconds)
        
        self.log_info("Service execution loop ended")

    def run_monitor_thread(self):
        """Run the async monitor in a separate thread."""
        try:
            # Create new event loop for this thread
            self.event_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.event_loop)
            
            # Set Windows-specific event loop policy
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            
            self.is_running = True
            
            # Run the monitoring
            self.event_loop.run_until_complete(self.run_async_monitor())
            
        except Exception as e:
            self.log_error(f"Monitor thread error: {e}\n{traceback.format_exc()}")
            raise
        finally:
            if self.event_loop and not self.event_loop.is_closed():
                self.event_loop.close()

    async def run_async_monitor(self):
        """Run the async monitoring loop."""
        try:
            # Initialize monitor
            self.monitor_instance = WatchMonitor(
                log_level="INFO",
                log_file="logs/watch_monitor_service.log"
            )
            
            await self.monitor_instance.initialize()
            self.log_info("Monitor initialized successfully")
            
            # Run continuous monitoring with service-aware loop
            await self.run_continuous_with_service_check()
            
        except Exception as e:
            self.log_error(f"Async monitor error: {e}")
            raise
        finally:
            if self.monitor_instance:
                try:
                    await self.monitor_instance.cleanup()
                    self.log_info("Monitor cleanup completed")
                except Exception as e:
                    self.log_error(f"Monitor cleanup error: {e}")

    async def run_continuous_with_service_check(self):
        """Run monitoring with periodic service status checks."""
        while self.is_running:
            try:
                # Run one monitoring cycle
                session = await self.monitor_instance.run_monitoring_cycle()
                
                self.log_info(
                    f"Monitoring cycle completed: {session.total_watches_found} watches found, "
                    f"{session.total_new_watches} new, {session.notifications_sent} notifications sent"
                )
                
                # Wait for check interval or stop signal
                check_interval = int(os.environ.get('CHECK_INTERVAL_SECONDS', '300'))
                
                for _ in range(check_interval):
                    if not self.is_running:
                        break
                    await asyncio.sleep(1)
                
            except Exception as e:
                self.log_error(f"Monitoring cycle error: {e}")
                # Don't break the loop for individual cycle errors
                await asyncio.sleep(60)  # Wait a minute before retrying

    async def shutdown_monitor(self):
        """Gracefully shutdown the monitor."""
        try:
            self.log_info("Shutting down monitor gracefully...")
            
            if self.monitor_instance:
                await self.monitor_instance.cleanup()
                
            self.log_info("Monitor shutdown completed")
            
        except Exception as e:
            self.log_error(f"Error during monitor shutdown: {e}")


def install_service():
    """Install the Windows service."""
    try:
        # Check if running as administrator
        if not win32api.GetUserName() or not win32serviceutil.QueryServiceStatus(None)[0]:
            print("❌ Administrator privileges required for service installation")
            print("💡 Run this script as administrator")
            return False
        
        print("🔧 Installing Watch Monitor Windows Service...")
        
        # Install the service
        win32serviceutil.InstallService(
            WatchMonitorService._exe_name_,
            WatchMonitorService._svc_name_,
            WatchMonitorService._svc_display_name_,
            exeArgs=WatchMonitorService._exe_args_,
            description=WatchMonitorService._svc_description_,
            startType=win32service.SERVICE_AUTO_START,  # Auto-start on boot
            dependencies=WatchMonitorService._svc_deps_
        )
        
        print(f"✅ Service '{WatchMonitorService._svc_display_name_}' installed successfully")
        print("   - Service will auto-start on Windows boot")
        print("   - Use 'python windows_service.py start' to start now")
        
        return True
        
    except Exception as e:
        print(f"❌ Service installation failed: {e}")
        return False


def main():
    """Main entry point for service management."""
    if len(sys.argv) == 1:
        # No arguments, show help
        print(__doc__)
        return
    
    command = sys.argv[1].lower()
    
    if command == "install":
        install_service()
    elif command == "debug":
        # Run in debug mode (interactive)
        print("🐛 Running in debug mode (Ctrl+C to stop)")
        service = WatchMonitorService([])
        service.is_running = True
        try:
            service.run_service()
        except KeyboardInterrupt:
            print("\n⏹️ Debug mode stopped by user")
            service.is_running = False
    else:
        # Handle standard service operations (start, stop, remove, etc.)
        try:
            win32serviceutil.HandleCommandLine(WatchMonitorService)
        except Exception as e:
            print(f"❌ Service operation failed: {e}")
            if "access is denied" in str(e).lower():
                print("💡 Run as administrator for service operations")


if __name__ == "__main__":
    main()