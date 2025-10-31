"""Base scraper class for watch monitor application."""

import asyncio
from abc import ABC, abstractmethod
from typing import List, Set, Optional, Dict, Any
from urllib.parse import urljoin
import aiohttp
from bs4 import BeautifulSoup

from config import SiteConfig, APP_CONFIG
from models import WatchData
from logging_config import ContextLogger, PerformanceLogger
from utils import fetch_page, parse_price, parse_year, parse_box_papers, parse_condition, extract_text_from_element


class BaseScraper(ABC):
    """Abstract base class for all watch scrapers."""
    
    def __init__(self, config: SiteConfig, session: aiohttp.ClientSession, logger):
        """
        Initialize scraper.
        
        Args:
            config: Site-specific configuration
            session: aiohttp session for requests
            logger: Logger instance
        """
        self.config = config
        self.session = session
        self.logger = ContextLogger(logger, {"site": config.key})
        self.seen_ids: Set[str] = set()
    
    def set_seen_ids(self, seen_ids: Set[str]):
        """Update the set of seen watch IDs."""
        self.seen_ids = seen_ids
    
    async def scrape(self) -> List[WatchData]:
        """
        Main scraping method.
        
        Returns:
            List of new watches found
        """
        with PerformanceLogger(self.logger.logger, f"scraping {self.config.name}"):
            soup = None
            try:
                # Fetch listing page
                self.logger.info(f"Fetching listing page: {self.config.url}")
                content = await fetch_page(self.session, self.config.url, self.logger.logger)
                
                if not content:
                    self.logger.error("Failed to fetch listing page")
                    return []
                
                # Parse watches
                soup = BeautifulSoup(content, 'html.parser')
                watches = await self._extract_watches(soup)
                
                # Clean up soup object immediately after parsing
                self._cleanup_soup(soup)
                soup = None
                
                self.logger.info(f"Found {len(watches)} watches on listing page")
                
                # Log sample composite IDs for debugging
                if watches and self.logger.logger.level <= 10:  # DEBUG level
                    self.logger.debug("Sample watch IDs for debugging:")
                    for watch in watches[:3]:
                        self.logger.debug(
                            f"  - {watch.title[:40]}... | Price: {watch.price_display or 'N/A'} | "
                            f"ID: {watch.composite_id[:12]}..."
                        )
                
                # Filter new watches
                new_watches = []
                for watch in watches:
                    composite_id = watch.composite_id
                    if composite_id not in self.seen_ids:
                        new_watches.append(watch)
                        self.seen_ids.add(composite_id)
                        self.logger.debug(f"New watch detected: {watch.title[:50]}... (ID: {composite_id[:8]}...)")
                    else:
                        self.logger.debug(f"Already seen: {watch.title[:50]}... (ID: {composite_id[:8]}...)")
                
                self.logger.info(f"Found {len(new_watches)} new watches (Total seen: {len(self.seen_ids)})")
                
                # Fetch details for new watches
                if new_watches and APP_CONFIG.enable_detail_scraping:
                    await self._fetch_watch_details(new_watches)
                
                return new_watches
                
            except Exception as e:
                self.logger.exception(f"Error during scraping: {e}")
                return []
            finally:
                # Ensure soup is cleaned up even if an exception occurs
                if soup is not None:
                    self._cleanup_soup(soup)
    
    @abstractmethod
    async def _extract_watches(self, soup: BeautifulSoup) -> List[WatchData]:
        """
        Extract watch data from listing page.
        
        Args:
            soup: BeautifulSoup of listing page
        
        Returns:
            List of WatchData objects
        """
        pass
    
    async def _fetch_watch_details(self, watches: List[WatchData]):
        """
        Fetch additional details for watches.
        
        Args:
            watches: List of watches to fetch details for
        """
        # Limit concurrent detail fetches
        semaphore = asyncio.Semaphore(APP_CONFIG.max_concurrent_details)
        
        async def fetch_single_detail(watch: WatchData):
            async with semaphore:
                try:
                    await self._fetch_single_watch_detail(watch)
                    # Add delay between requests
                    await asyncio.sleep(APP_CONFIG.detail_page_delay)
                except Exception as e:
                    self.logger.error(f"Error fetching details for {watch.url}: {e}")
        
        # Fetch all details concurrently
        tasks = [fetch_single_detail(watch) for watch in watches]
        await asyncio.gather(*tasks)
    
    async def _fetch_single_watch_detail(self, watch: WatchData):
        """
        Fetch details for a single watch.
        
        Args:
            watch: Watch to fetch details for
        """
        self.logger.debug(f"Fetching details for: {watch.url}")
        
        content = await fetch_page(self.session, watch.url, self.logger.logger)
        if not content:
            return
        
        soup = None
        try:
            soup = BeautifulSoup(content, 'html.parser')
            
            # Call site-specific detail extraction
            await self._extract_watch_details(watch, soup)
            
            watch.detail_scraped = True
        finally:
            # Clean up soup object after use
            if soup is not None:
                self._cleanup_soup(soup)
    
    async def _extract_watch_details(self, watch: WatchData, soup: BeautifulSoup):
        """
        Extract additional details from watch detail page.
        Override in subclasses for site-specific logic.
        
        Args:
            watch: Watch object to update
            soup: BeautifulSoup of detail page
        """
        pass
    
    def _cleanup_soup(self, soup: BeautifulSoup):
        """
        Explicitly clean up BeautifulSoup object to release memory.
        
        Args:
            soup: BeautifulSoup object to clean up
        """
        if soup is not None:
            try:
                # Decompose the soup tree to break circular references
                soup.decompose()
            except Exception as e:
                self.logger.debug(f"Error during soup cleanup: {e}")
    
    # Common parsing helpers
    
    def _parse_price_text(self, element) -> Optional[str]:
        """Extract price text from element."""
        if not element:
            return None
        
        # Try different methods to get price
        price_text = None
        
        # Method 1: Direct text
        if hasattr(element, 'get_text'):
            price_text = element.get_text(strip=True)
        
        # Method 2: Specific attributes
        if not price_text and hasattr(element, 'attrs'):
            for attr in ['data-price', 'content', 'value']:
                if attr in element.attrs:
                    price_text = element.attrs[attr]
                    break
        
        return price_text
    
    def _extract_brand_model(self, title: str) -> tuple[Optional[str], Optional[str]]:
        """
        Extract brand and model from title using known brands.
        
        Args:
            title: Watch title
        
        Returns:
            Tuple of (brand, model)
        """
        if not title:
            return None, None
        
        title_lower = title.lower()
        
        # Check known brands
        for brand_lower, brand_proper in self.config.known_brands.items():
            if title_lower.startswith(brand_lower):
                # Extract model as remainder after brand
                model_text = title[len(brand_lower):].strip()
                
                # Clean up model text
                if model_text.startswith('-') or model_text.startswith('|'):
                    model_text = model_text[1:].strip()
                
                return brand_proper, model_text if model_text else None
        
        # If no known brand, try to split by common patterns
        # This is a fallback and may not be accurate
        parts = title.split(' ', 1)
        if len(parts) >= 2:
            return parts[0], parts[1]
        
        return title, None
    
    def _build_absolute_url(self, url: str) -> str:
        """Convert relative URL to absolute."""
        if not url:
            return ""
        
        if url.startswith(('http://', 'https://')):
            return url
        
        return urljoin(self.config.base_url, url)
    
    def _clean_reference(self, ref: str) -> Optional[str]:
        """Clean and validate reference number."""
        if not ref:
            return None
        
        # Remove common prefixes
        ref = ref.upper()
        for prefix in ['REF.', 'REF', 'REFERENCE', 'MODEL']:
            if ref.startswith(prefix):
                ref = ref[len(prefix):].strip()
        
        # Remove special characters but keep alphanumeric and dashes
        import re
        ref = re.sub(r'[^\w\-.]', '', ref)
        
        return ref if ref else None