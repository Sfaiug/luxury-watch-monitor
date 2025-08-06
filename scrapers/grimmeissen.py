"""Grimmeissen scraper implementation."""

import re
from typing import List, Optional
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from scrapers.base import BaseScraper
from models import WatchData
from utils import parse_price, parse_year, parse_box_papers, parse_condition, extract_text_from_element, parse_table_data


class GrimmeissenScraper(BaseScraper):
    """Scraper for Grimmeissen website."""
    
    async def _extract_watches(self, soup: BeautifulSoup) -> List[WatchData]:
        """Extract watches from Grimmeissen listing page."""
        watches = []
        
        # Use exact selectors from original implementation
        watch_elements = soup.select('article.watch')
        
        for watch_tag in watch_elements:
            try:
                watch = self._parse_watch_element(watch_tag)
                if watch:
                    watches.append(watch)
            except Exception as e:
                self.logger.error(f"Error parsing watch element: {e}")
        
        return watches
    
    def _parse_watch_element(self, watch_tag) -> Optional[WatchData]:
        """Parse a single watch element from listing page - matching original logic exactly."""
        
        # Extract URL
        link_tag_listing = watch_tag.select_one('figure a')
        if not link_tag_listing or not link_tag_listing.has_attr('href'):
            return None
        
        url = urljoin(self.config.base_url, link_tag_listing['href'])
        
        # Extract image URL
        img_tag_listing = watch_tag.select_one('figure a img')
        image_url = None
        if img_tag_listing and img_tag_listing.has_attr('data-src'):
            image_url = urljoin(self.config.base_url, img_tag_listing['data-src'])
        
        # Extract title from listing
        title_listing_tag = watch_tag.select_one('section.fh h1')
        title = extract_text_from_element(title_listing_tag) if title_listing_tag else "Unknown Watch"
        
        # Extract brand from title (original logic)
        brand = None
        model = None
        if title_listing_tag:
            brand_tag = title_listing_tag.select_one("span a")
            if brand_tag:
                brand = extract_text_from_element(brand_tag)
                # Extract model by removing brand from title
                model = extract_text_from_element(title_listing_tag, separator=" ").replace(brand, "").strip()
            else:
                model = title
        
        # Extract price from listing
        price_listing_tag = watch_tag.select_one('section.fh p')
        price = None
        if price_listing_tag:
            price_text_raw = extract_text_from_element(price_listing_tag)
            if price_text_raw:
                price = parse_price(price_text_raw, "EUR")
        
        # Create watch data
        return WatchData(
            title=title,
            url=url,
            site_name=self.config.name,
            site_key=self.config.key,
            brand=brand,
            model=model,
            price=price,
            currency="EUR",
            image_url=image_url
        )
    
    async def _extract_watch_details(self, watch: WatchData, soup: BeautifulSoup):
        """Extract additional details from Grimmeissen detail page - matching original exactly."""
        
        # Update title and brand from detail page if available
        title_detail_tag = soup.select_one("div.c-7.do-lefty h1.lowpad-b")
        if title_detail_tag:
            watch.title = extract_text_from_element(title_detail_tag)
            
            # Extract brand from detail page
            brand_detail_tag = title_detail_tag.select_one("span a")
            if brand_detail_tag:
                watch.brand = extract_text_from_element(brand_detail_tag)
                # Update model by removing brand from title
                watch.model = extract_text_from_element(title_detail_tag, separator=" ").replace(watch.brand, "").strip()
        
        # Parse details from tables - exact mapping from original
        details_container = soup.select_one("div.c-7.do-lefty")
        if details_container:
            # First table with main details
            table1_map = {
                "Referenz": "reference", 
                "Zustand": "condition_text_raw", 
                "Gehäuse": "case_material", 
                "Jahr": "year_text", 
                "Durchmesser": "diameter"
            }
            
            table1 = details_container.select_one("table:nth-of-type(1)")
            table1_data = self._parse_details_from_table_th_td(table1, table1_map)
            
            # Extract reference
            if table1_data.get("reference"):
                watch.reference = table1_data["reference"]
            
            # Extract condition
            if table1_data.get("condition_text_raw"):
                watch.condition = parse_condition(
                    table1_data["condition_text_raw"], 
                    self.config.key, 
                    self.config.condition_mappings
                )
            
            # Extract case material
            if table1_data.get("case_material"):
                watch.case_material = table1_data["case_material"]
            
            # Parse year
            if table1_data.get("year_text"):
                watch.year = parse_year(table1_data["year_text"], watch.title or "")
            
            # Extract diameter
            if table1_data.get("diameter"):
                watch.diameter = table1_data["diameter"]
            
            # Look for second table with "Details" section for box/papers info
            h3_details_tag = details_container.find('h3', string=re.compile(r'Details', re.I))
            lieferumfang_text = ""
            
            if h3_details_tag:
                table2 = h3_details_tag.find_next_sibling('table')
                if table2:
                    table2_data = self._parse_details_from_table_th_td(table2, {"Lieferumfang": "lieferumfang_text"})
                    lieferumfang_text = table2_data.get("lieferumfang_text", "")
            
            # Parse box and papers status
            has_papers, has_box = parse_box_papers(lieferumfang_text)
            if has_papers is not None:
                watch.has_papers = has_papers
            if has_box is not None:
                watch.has_box = has_box
    
    def _parse_details_from_table_th_td(self, container, headers_map: dict) -> dict:
        """Parse details from table with th/td structure - matching original logic."""
        details = {}
        
        if not container:
            return details
        
        try:
            # Find all table rows with th and td
            for row in container.select("tr"):
                th_elem = row.select_one("th")
                td_elem = row.select_one("td")
                
                if th_elem and td_elem:
                    # Clean header text and remove colon
                    header = extract_text_from_element(th_elem).replace(":", "").strip()
                    value = extract_text_from_element(td_elem)
                    
                    if header in headers_map and value:
                        details[headers_map[header]] = value
        
        except Exception as e:
            self.logger.warning(f"Error parsing details table: {e}")
        
        return details