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

        # Updated selector for new website structure (2025+)
        watch_elements = soup.select('div.product-list-item.card.product-box')

        for item_tag in watch_elements:
            try:
                watch = self._parse_watch_element(item_tag)
                if watch:
                    watches.append(watch)
            except Exception as e:
                self.logger.error(f"Error parsing watch element: {e}")
        
        return watches
    
    def _parse_watch_element(self, item_tag) -> Optional[WatchData]:
        """Parse a single watch element from listing page - updated for 2025 website structure."""

        # Extract URL and title from the main card link
        link_tag = item_tag.select_one('a.card-body')
        if not (link_tag and link_tag.has_attr('href')):
            return None

        url = link_tag['href']
        if not url.startswith('http'):
            url = urljoin(self.config.base_url, url)

        # Get title from data-title attribute
        full_title_from_listing = link_tag.get('data-title', 'Unknown Watch')

        # Extract image URL
        img_tag = item_tag.select_one('img.product-image')
        image_url = None
        if img_tag:
            # Prefer srcset for higher resolution, fallback to src
            srcset = img_tag.get('srcset', '')
            if srcset:
                # Get the highest resolution from srcset
                sources = [s.strip().split(' ')[0] for s in srcset.split(',') if s.strip()]
                if sources:
                    image_url = sources[-1]  # Last one is usually highest res
            if not image_url:
                image_url = img_tag.get('src')
            if image_url and not image_url.startswith('http'):
                image_url = urljoin(self.config.base_url, image_url)

        # Extract brand, model, and reference from URL slug
        # URL format: /brand-model-reference-sku-certified-pre-owned
        brand = None
        model = None
        reference = None

        # Parse URL path for watch details
        url_path = url.split('/')[-1] if '/' in url else ''
        if url_path and 'certified-pre-owned' in url_path:
            # Remove the "certified-pre-owned" suffix
            slug_parts = url_path.replace('-certified-pre-owned', '').split('-')

            # Known watch brands (lowercase)
            known_brands = {
                'rolex': 'Rolex', 'omega': 'Omega', 'patek': 'Patek Philippe',
                'audemars': 'Audemars Piguet', 'cartier': 'Cartier', 'iwc': 'IWC',
                'breitling': 'Breitling', 'panerai': 'Panerai', 'tudor': 'Tudor',
                'jaeger': 'Jaeger-LeCoultre', 'hublot': 'Hublot', 'tag': 'TAG Heuer',
                'vacheron': 'Vacheron Constantin', 'zenith': 'Zenith', 'longines': 'Longines',
                'tissot': 'Tissot', 'seiko': 'Seiko', 'grand': 'Grand Seiko',
                'chopard': 'Chopard', 'girard': 'Girard-Perregaux', 'blancpain': 'Blancpain',
                'glashutte': 'Glashütte Original', 'a': 'A. Lange & Söhne'
            }

            if slug_parts:
                # First part is typically the brand
                first_part = slug_parts[0].lower()
                brand = known_brands.get(first_part, slug_parts[0].title())

                # Try to extract reference from data-product-number attribute
                price_wrapper = item_tag.select_one('[data-product-number]')
                if price_wrapper:
                    product_number = price_wrapper.get('data-product-number', '')
                    # Format: "16710#*510918" -> reference is "16710"
                    if '#*' in product_number:
                        reference = product_number.split('#*')[0]
                    elif product_number:
                        reference = product_number

                # Extract model from slug (parts between brand and reference)
                if len(slug_parts) > 2:
                    # Find where the reference starts in the slug
                    model_parts = []
                    for part in slug_parts[1:]:
                        # Stop when we hit the reference or SKU (usually numeric)
                        if reference and part == reference.lower():
                            break
                        if part.isdigit() and len(part) >= 5:  # Likely SKU
                            break
                        model_parts.append(part)
                    if model_parts:
                        model = ' '.join(model_parts).title().replace('-', ' ')

        # Fallback: extract reference from title if not found
        if not reference and full_title_from_listing:
            ref_match = re.match(r'^([A-Za-z0-9\-./]+)', full_title_from_listing)
            if ref_match:
                potential_ref = ref_match.group(1)
                if not (potential_ref.lower() == "certified" or
                       (potential_ref.isdigit() and len(potential_ref) < 4)):
                    reference = potential_ref

        # Extract price
        price = None
        price_tag = item_tag.select_one('span.product-price')
        if price_tag:
            price_text_raw = extract_text_from_element(price_tag)
            # Clean up: may contain both sale price and original price
            # Take the first price value (current price)
            if price_text_raw:
                price = parse_price(price_text_raw, "EUR")

        # Set condition based on CPO badge
        condition = None
        if item_tag.select_one('div.badge-cpo, .badge.badge-cpo'):
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