"""Tropical Watch scraper implementation."""

import re
from typing import List, Optional
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from decimal import Decimal

from scrapers.base import BaseScraper
from models import WatchData
from utils import parse_price, parse_year, parse_box_papers, parse_condition, extract_text_from_element, get_usd_to_eur_rate
from config import APP_CONFIG


class TropicalWatchScraper(BaseScraper):
    """Scraper for Tropical Watch website."""
    
    async def scrape(self) -> List[WatchData]:
        """Override scrape to add USD to EUR conversion."""
        # Call parent scrape method
        new_watches = await super().scrape()
        
        # Convert USD prices to EUR if enabled
        if APP_CONFIG.enable_exchange_rate_conversion and new_watches:
            exchange_rate = await get_usd_to_eur_rate(self.session, self.logger.logger)
            
            if exchange_rate:
                self.logger.info(f"Converting USD prices to EUR (rate: 1 USD = {exchange_rate:.4f} EUR)")
                
                for watch in new_watches:
                    if watch.currency == "USD" and watch.price:
                        # Store original USD price for logging
                        usd_price = watch.price
                        # Convert price from USD to EUR (both as Decimal)
                        watch.price = watch.price * Decimal(str(exchange_rate))
                        watch.currency = "EUR"
                        # Update the display format to show EUR
                        watch.price_display = watch._format_price_display()
                        self.logger.debug(f"Converted price for {watch.title}: ${usd_price:.0f} USD → €{watch.price:.0f} EUR")
            else:
                self.logger.warning("Could not fetch USD to EUR exchange rate, prices remain in USD")
        
        return new_watches
    
    async def _extract_watches(self, soup: BeautifulSoup) -> List[WatchData]:
        """Extract watches from Tropical Watch listing page."""
        watches = []
        
        # Use exact selectors from original implementation
        watch_elements = soup.select('li.watch')
        
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
        link_tag_wrapper = watch_tag.select_one('div.photo-wrapper a')
        if not link_tag_wrapper or not link_tag_wrapper.has_attr('href'):
            return None
        
        url = urljoin(self.config.base_url, link_tag_wrapper['href'])
        
        # Extract title from listing
        title_listing_tag = watch_tag.select_one('div.content a h2')
        title = extract_text_from_element(title_listing_tag) if title_listing_tag else "Unknown Watch"
        
        # Extract USD price (original uses USD and converts to EUR)
        price_usd_tag = watch_tag.select_one('div.content a h3')
        price_usd_text_raw = extract_text_from_element(price_usd_tag) if price_usd_tag else ""
        
        # Extract price in USD format (will be converted to EUR later if needed)
        price = None
        if price_usd_text_raw:
            try:
                # Clean price text to extract numeric value
                price_clean = re.sub(r'[^\d.]', '', price_usd_text_raw)
                if price_clean:
                    price = parse_price(price_clean, "USD")
            except:
                pass
        
        # Extract image URL
        img_tag_listing = watch_tag.select_one('div.photo-wrapper a img')
        image_url = None
        if img_tag_listing and img_tag_listing.has_attr('src'):
            image_url = urljoin(self.config.base_url, img_tag_listing['src'])
        
        # Create watch data with initial values
        return WatchData(
            title=title,
            url=url,
            site_name=self.config.name,
            site_key=self.config.key,
            brand=None,  # Will be extracted from detail page
            model=None,  # Will be extracted from detail page
            price=price,
            currency="USD",  # Original uses USD
            image_url=image_url
        )
    
    async def _extract_watch_details(self, watch: WatchData, soup: BeautifulSoup):
        """Extract additional details from Tropical Watch detail page - matching original exactly."""
        
        # Update title from detail page if available
        title_detail_tag = soup.select_one("h1.watch-main-title")
        if title_detail_tag:
            watch.title = extract_text_from_element(title_detail_tag)
        
        # Parse details table - exact mapping from original
        details_table_map = {
            "Year": "year_text", 
            "Brand": "brand_table", 
            "Model": "model_table", 
            "Reference": "reference_text", 
            "Case Material": "case_material_table", 
            "Diameter": "diameter_table"
        }
        
        details_table_container = soup.select_one("div.watch-main-details-content table.watch-main-details-table")
        table_details = self._parse_details_from_table_th_td(details_table_container, details_table_map)
        
        # Extract brand from table
        if table_details.get("brand_table"):
            watch.brand = table_details["brand_table"]
        
        # Extract model from table
        if table_details.get("model_table"):
            watch.model = table_details["model_table"]
        
        # Parse year
        if table_details.get("year_text"):
            watch.year = parse_year(table_details["year_text"], watch.title or "")
        
        # Extract reference
        if table_details.get("reference_text"):
            watch.reference = table_details["reference_text"]
        
        # Extract case material
        if table_details.get("case_material_table"):
            watch.case_material = table_details["case_material_table"]
        
        # Extract diameter
        if table_details.get("diameter_table"):
            watch.diameter = table_details["diameter_table"]
        
        # Fallback brand extraction if not found in table - matching original logic
        if not watch.brand and watch.title:
            known_brands_tw = [
                "Rolex", "Patek Philippe", "Audemars Piguet", "Omega", "Tudor", 
                "Heuer", "Studio Underd0g", "Longines", "Jaeger-LeCoultre", "Zenith", 
                "IWC", "Panerai", "Cartier", "Breitling", "Universal Geneve", "A. Lange & Söhne"
            ]
            title_l_for_brand = watch.title.lower()
            
            # Check if title starts with brand name
            for b_name in sorted(known_brands_tw, key=len, reverse=True):
                if title_l_for_brand.startswith(b_name.lower()):
                    watch.brand = b_name
                    break
            
            # If not found, check if brand name is anywhere in title
            if not watch.brand:
                for b_name in sorted(known_brands_tw, key=len, reverse=True):
                    if b_name.lower() in title_l_for_brand:
                        watch.brand = b_name
                        break
        
        # Extract model from title if not found in table - matching original logic
        if not watch.model and watch.brand and watch.title:
            temp_model_str = re.sub(fr"^{re.escape(watch.brand)}\s*", "", watch.title, flags=re.IGNORECASE).strip()
            
            # Remove year from model string
            year_in_title = parse_year("", temp_model_str)
            if year_in_title:
                temp_model_str = temp_model_str.replace(year_in_title, "").strip()
            
            # Remove reference from model string
            ref_in_title_val = watch.reference if watch.reference else table_details.get("reference_text", "")
            if ref_in_title_val and ref_in_title_val.lower() in temp_model_str.lower():
                temp_model_str = re.sub(re.escape(ref_in_title_val), "", temp_model_str, flags=re.IGNORECASE).strip()
            
            # Take first 3 words as model
            model_words = [word for word in temp_model_str.split() if not (word.isdigit() and len(word) == 4)]
            model_candidate = " ".join(model_words[:3]).title().strip()
            
            if model_candidate and model_candidate.lower() != watch.brand.lower():
                watch.model = model_candidate
        
        # Extract reference from title if not found in table - matching original logic
        if not watch.reference and watch.title:
            temp_ref_search_str = watch.title
            
            # Remove brand from search string
            if watch.brand:
                temp_ref_search_str = re.sub(re.escape(watch.brand), "", temp_ref_search_str, flags=re.IGNORECASE)
            
            # Remove model from search string
            if watch.model:
                temp_ref_search_str = re.sub(re.escape(watch.model), "", temp_ref_search_str, flags=re.IGNORECASE)
            
            # Remove year from search string
            year_val_for_ref = parse_year("", temp_ref_search_str)
            if year_val_for_ref:
                temp_ref_search_str = temp_ref_search_str.replace(year_val_for_ref, "")
            
            # Look for reference pattern
            ref_match_title = re.search(r'\b([A-Z0-9]{3,}(?:[-/\s]?[A-Z0-9]+)?)\b', temp_ref_search_str.strip())
            if ref_match_title and not re.fullmatch(r'\d{4}', ref_match_title.group(1)):
                watch.reference = ref_match_title.group(1)
        
        # Parse accessories and condition from description - matching original logic
        accessories_text, condition_desc_parts = "", []
        description_container = soup.select_one("div.watch-main-description")
        
        if description_container:
            for p_tag in description_container.find_all('p'):
                strong_tag = p_tag.find('strong')
                p_text_content = extract_text_from_element(p_tag)
                
                if strong_tag:
                    strong_text_clean = extract_text_from_element(strong_tag).lower()
                    if "accessories:" in strong_text_clean:
                        accessories_text = p_text_content.lower().replace("accessories:", "").strip()
                    elif any(k in strong_text_clean for k in ["case:", "dial:", "bracelet:", "movement:", "condition:"]):
                        condition_desc_parts.append(p_text_content)
                else:
                    condition_desc_parts.append(p_text_content)
        
        # Parse box and papers status
        has_papers, has_box = parse_box_papers(accessories_text)
        if has_papers is not None:
            watch.has_papers = has_papers
        if has_box is not None:
            watch.has_box = has_box
        
        # Set condition based on description parts
        if condition_desc_parts:
            watch.condition = parse_condition(" ".join(condition_desc_parts), self.config.key)
        
        # Extract case material from title if not found in table - matching original logic
        if not watch.case_material and watch.title:
            title_l = watch.title.lower()
            if "18k wg" in title_l or "white gold" in title_l:
                watch.case_material = "White Gold"
            elif "18k yg" in title_l or "yellow gold" in title_l:
                watch.case_material = "Yellow Gold"
            elif "18k pg" in title_l or "pink gold" in title_l or "rose gold" in title_l:
                watch.case_material = "Rose Gold"
            elif "steel" in title_l or "stainless" in title_l:
                watch.case_material = "Steel"
            elif "gold" in title_l:
                watch.case_material = "Gold"
        
        # Extract diameter from description if not found in table - matching original logic
        if not watch.diameter:
            desc_text_for_dia = " ".join([watch.title] + condition_desc_parts if condition_desc_parts else [watch.title])
            dia_match = re.search(r'(\d{2}(?:\.\d+)?)\s*mm', desc_text_for_dia, re.IGNORECASE)
            if dia_match:
                watch.diameter = dia_match.group(1) + "mm"
    
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