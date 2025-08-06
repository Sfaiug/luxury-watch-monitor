"""Rüschenbeck scraper implementation."""

import re
from typing import List, Optional
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from scrapers.base import BaseScraper
from models import WatchData
from utils import parse_price, parse_year, parse_box_papers, parse_condition, extract_text_from_element


class RueschenbeckScraper(BaseScraper):
    """Scraper for Rüschenbeck website."""
    
    async def _extract_watches(self, soup: BeautifulSoup) -> List[WatchData]:
        """Extract watches from Rüschenbeck listing page."""
        watches = []
        
        # Use exact selectors from original implementation
        watch_elements = soup.select('li.-rb-list-item')
        
        for item_tag in watch_elements:
            try:
                watch = self._parse_watch_element(item_tag)
                if watch:
                    watches.append(watch)
            except Exception as e:
                self.logger.error(f"Error parsing watch element: {e}")
        
        return watches
    
    def _parse_watch_element(self, item_tag) -> Optional[WatchData]:
        """Parse a single watch element from listing page - matching original logic exactly."""
        
        # Skip sold items
        availability_div = item_tag.select_one('.-rb-availability .out-of-stock span.value, .-rb-availability .sold span.value')
        if availability_div and "verkauft" in extract_text_from_element(availability_div).lower():
            return None
        
        # Extract URL
        link_tag = item_tag.select_one('a.-rb-list-item-link')
        if not (link_tag and link_tag.has_attr('href')):
            return None
        
        url = urljoin(self.config.base_url, link_tag['href'])
        
        # Extract image URL
        img_tag = item_tag.select_one('.-rb-list-image img')
        image_url = None
        if img_tag and img_tag.has_attr('src'):
            image_url = urljoin(self.config.base_url, img_tag['src'])
        
        # Extract brand
        brand_elem = item_tag.select_one('span.-rb-manufacturer-name')
        brand = extract_text_from_element(brand_elem) if brand_elem else None
        
        # Extract model
        model_elem = item_tag.select_one('span.-rb-line-name')
        model = extract_text_from_element(model_elem) if model_elem else None
        
        # Extract title and reference from product name
        prod_name_tag = item_tag.select_one('span.-rb-prod-name')
        full_title_from_listing = extract_text_from_element(prod_name_tag) if prod_name_tag else "Unknown Watch"
        
        # Extract reference from title using original logic
        reference = None
        if full_title_from_listing:
            ref_match = re.match(r'^([A-Za-z0-9\-./]+)', full_title_from_listing)
            if ref_match:
                potential_ref = ref_match.group(1)
                if not (potential_ref.lower() == "certified" or 
                       (potential_ref.isdigit() and len(potential_ref) < 4)):
                    reference = potential_ref
        
        # Extract price
        price_box = item_tag.select_one('.price-box')
        price = None
        if price_box:
            # Check for special price first, then regular price
            special_price_tag = price_box.select_one('p.special-price span.price')
            regular_price_tag = price_box.select_one('span.regular-price span.price')
            
            price_text_raw = None
            if special_price_tag:
                price_text_raw = extract_text_from_element(special_price_tag)
            elif regular_price_tag:
                price_text_raw = extract_text_from_element(regular_price_tag)
            
            if price_text_raw:
                price = parse_price(price_text_raw, "EUR")
        
        # Set initial condition based on certification badge
        condition = None
        if item_tag.select_one('span.-rb-icon.icn-cpo'):
            condition = "★★★★☆"  # CPO (Certified Pre-Owned) condition
        
        # Create watch data
        return WatchData(
            title=full_title_from_listing,
            url=url,
            site_name=self.config.name,
            site_key=self.config.key,
            brand=brand,
            model=model,
            reference=reference,
            price=price,
            currency="EUR",
            condition=condition,
            image_url=image_url
        )
    
    async def _extract_watch_details(self, watch: WatchData, soup: BeautifulSoup):
        """Extract additional details from Rüschenbeck detail page - matching original exactly."""
        
        # Update title from detail page
        detail_title_tag = soup.select_one('div.product-name h1 span.prod-name')
        if detail_title_tag:
            watch.title = extract_text_from_element(detail_title_tag)
        
        # Update brand from detail page
        detail_brand_tag = soup.select_one('div.product-name h1 span.manufacturer-name')
        if detail_brand_tag:
            watch.brand = extract_text_from_element(detail_brand_tag)
        
        # Update model from detail page
        detail_model_tag = soup.select_one('div.product-name h1 span.line-name')
        if detail_model_tag:
            watch.model = extract_text_from_element(detail_model_tag)
        
        # Parse additional details
        parsed_details = self._parse_rueschenbeck_details(soup)
        
        # Extract year
        if parsed_details.get("year_text"):
            year_val = parse_year(parsed_details["year_text"], watch.title or "")
            if year_val:
                watch.year = year_val
        
        # Extract reference (prefer longer/more detailed reference)
        if (parsed_details.get("reference_text") and 
            (not watch.reference or len(parsed_details["reference_text"]) > len(watch.reference))):
            watch.reference = parsed_details["reference_text"].strip()
        
        # Extract diameter
        if parsed_details.get("diameter_text"):
            dia_text = parsed_details["diameter_text"]
            dia_match = re.search(r'(\d{1,2}(?:[.,]\d{1,2})?)\s*mm', dia_text, re.IGNORECASE)
            if dia_match:
                watch.diameter = dia_match.group(1).replace(",", ".") + "mm"
            else:
                # Try to clean and validate diameter
                cleaned_dia = dia_text.replace("mm", "").strip().replace(",", ".").replace(" ", "")
                if re.match(r'^\d+(\.\d+)?$', cleaned_dia):
                    watch.diameter = cleaned_dia + "mm"
                else:
                    watch.diameter = dia_text
        
        # Extract case material
        if parsed_details.get("case_material_text"):
            watch.case_material = parsed_details["case_material_text"].title()
        
        # Parse box and papers from detailed information
        all_detail_text = " ".join([
            parsed_details.get("description_text", ""),
            parsed_details.get("condition_text", ""),
            parsed_details.get("accessories_text", "")
        ])
        
        has_papers, has_box = parse_box_papers(all_detail_text)
        if has_papers is not None:
            watch.has_papers = has_papers
        if has_box is not None:
            watch.has_box = has_box
        
        # Update condition if we have more detailed information
        if parsed_details.get("condition_text"):
            condition = parse_condition(parsed_details["condition_text"], self.config.key)
            if condition:
                watch.condition = condition
    
    def _parse_rueschenbeck_details(self, soup: BeautifulSoup) -> dict:
        """Parse detailed information from Rüschenbeck detail page - matching original helper function."""
        parsed_details = {}
        
        try:
            # Look for product details in various sections
            
            # Check for specifications table/list
            specs_container = soup.select_one('div.product-specifications, div.product-details, .product-info')
            if specs_container:
                # Parse any tables in the specs container
                for table in specs_container.select('table'):
                    for row in table.select('tr'):
                        cells = row.select('th, td')
                        if len(cells) >= 2:
                            label = extract_text_from_element(cells[0]).lower().strip().replace(":", "")
                            value = extract_text_from_element(cells[1]).strip()
                            
                            if any(keyword in label for keyword in ["jahr", "year", "baujahr"]):
                                parsed_details["year_text"] = value
                            elif any(keyword in label for keyword in ["referenz", "reference", "ref"]):
                                parsed_details["reference_text"] = value
                            elif any(keyword in label for keyword in ["durchmesser", "diameter", "größe"]):
                                parsed_details["diameter_text"] = value
                            elif any(keyword in label for keyword in ["material", "gehäuse"]):
                                parsed_details["case_material_text"] = value
                            elif any(keyword in label for keyword in ["zustand", "condition"]):
                                parsed_details["condition_text"] = value
                
                # Also parse definition lists (dl/dt/dd)
                for dl in specs_container.select('dl'):
                    dt_elements = dl.select('dt')
                    dd_elements = dl.select('dd')
                    
                    for dt, dd in zip(dt_elements, dd_elements):
                        if dt and dd:
                            label = extract_text_from_element(dt).lower().strip().replace(":", "")
                            value = extract_text_from_element(dd).strip()
                            
                            if any(keyword in label for keyword in ["jahr", "year", "baujahr"]):
                                parsed_details["year_text"] = value
                            elif any(keyword in label for keyword in ["referenz", "reference", "ref"]):
                                parsed_details["reference_text"] = value
                            elif any(keyword in label for keyword in ["durchmesser", "diameter", "größe"]):
                                parsed_details["diameter_text"] = value
                            elif any(keyword in label for keyword in ["material", "gehäuse"]):
                                parsed_details["case_material_text"] = value
                            elif any(keyword in label for keyword in ["zustand", "condition"]):
                                parsed_details["condition_text"] = value
            
            # Look for description sections
            description_container = soup.select_one('div.product-description, div.description, .product-details-description')
            if description_container:
                parsed_details["description_text"] = extract_text_from_element(description_container)
            
            # Look for condition information
            condition_container = soup.select_one('div.product-condition, .condition-info')
            if condition_container:
                parsed_details["condition_text"] = extract_text_from_element(condition_container)
            
            # Look for accessories/scope of delivery information
            accessories_container = soup.select_one('div.product-accessories, .lieferumfang, .scope-delivery')
            if accessories_container:
                parsed_details["accessories_text"] = extract_text_from_element(accessories_container)
        
        except Exception as e:
            self.logger.warning(f"Error parsing Rüschenbeck details: {e}")
        
        return parsed_details