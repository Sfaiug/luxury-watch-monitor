"""World of Time scraper implementation."""

import re
from typing import List, Optional
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from scrapers.base import BaseScraper
from models import WatchData
from utils import parse_price, parse_year, parse_box_papers, parse_condition, extract_text_from_element


class WorldOfTimeScraper(BaseScraper):
    """Scraper for worldoftime.de website."""
    
    async def _extract_watches(self, soup: BeautifulSoup) -> List[WatchData]:
        """Extract watches from World of Time listing page."""
        watches = []
        
        # Use exact selectors from original implementation
        watch_elements = soup.select('div.new-arrivals-watch, div.paged-clocks-container div.watch-link')
        
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
        
        # Extract URL
        link_tag = item_tag.select_one('div.image a, div > a:has(img)')
        if not link_tag or not link_tag.has_attr('href'):
            return None
        
        url = urljoin(self.config.base_url, link_tag['href'])
        
        # Extract title using exact original selector
        title_tag = item_tag.select_one("div.text-truncate[style*='font-size: 17px'][style*='font-family: \\'AB\\'']")
        full_title = extract_text_from_element(title_tag) if title_tag else "Unknown Watch"
        
        # Extract brand and model using original logic
        known_brands = {
            "patek philippe": "Patek Philippe", 
            "rolex vintage": "Rolex", 
            "rolex": "Rolex", 
            "omega": "Omega", 
            "iwc": "IWC", 
            "jaeger lecoultre": "Jaeger LeCoultre", 
            "cartier": "Cartier", 
            "breitling": "Breitling", 
            "audemars piguet": "Audemars Piguet", 
            "heuer": "Heuer", 
            "universal geneve": "Universal Genève", 
            "panerai": "Panerai", 
            "tudor": "Tudor", 
            "longines": "Longines", 
            "zenith": "Zenith", 
            "a. lange & söhne": "A. Lange & Söhne"
        }
        
        parsed_brand, parsed_model = None, None
        
        if full_title:
            title_lower = full_title.lower()
            found_brand_proper = None
            
            # Check if title starts with known brand (sorted by length descending)
            for kb_lower, kb_proper in sorted(known_brands.items(), key=lambda item: len(item[0]), reverse=True):
                if title_lower.startswith(kb_lower):
                    parsed_brand, found_brand_proper = kb_proper, kb_proper
                    break
            
            if parsed_brand and found_brand_proper:
                # Extract model text after brand
                model_text = re.sub(fr"^{re.escape(found_brand_proper)}", "", full_title, flags=re.IGNORECASE).strip()
                parsed_model = model_text if model_text else None
                
                # Special handling for Rolex vintage
                if parsed_brand == "Rolex" and "vintage" in title_lower:
                    parsed_model = f"Vintage {parsed_model.replace('Vintage','').strip()}" if parsed_model else "Vintage"
            
            elif title_words := full_title.split():
                # Check for two-word brand names
                if (len(title_words) > 2 and 
                    (title_words[0] + " " + title_words[1]).lower() in known_brands):
                    parsed_brand = known_brands[(title_words[0] + " " + title_words[1]).lower()]
                    parsed_model = " ".join(title_words[2:]) if len(title_words) > 2 else None
                else:
                    # Fallback: first word as brand, rest as model
                    parsed_brand = title_words[0]
                    parsed_model = " ".join(title_words[1:]) if len(title_words) > 1 else None
        
        # Extract reference using original logic
        ref_container = None
        if title_tag:
            ref_container = title_tag.find_next_sibling("div", class_="text-truncate", 
                                                       style=lambda x: x and "font-size: 16px" in x)
        
        reference = None
        if ref_container:
            ref_val = extract_text_from_element(ref_container).replace("Ref.", "").strip()
            if ref_val and ref_val != " " and "Wot-ID" not in ref_val:
                reference = ref_val
        
        # Extract price using original selectors
        price_p_tag = item_tag.select_one("div.pt-4.mt-auto p, p.m-0.price[style*='font-size: 17px']")
        price = None
        if price_p_tag:
            price_text_raw = extract_text_from_element(price_p_tag)
            if price_text_raw:
                price = parse_price(price_text_raw, "EUR")
        
        # Extract image URL
        img_tag = item_tag.select_one('div.image img, div.square-container img')
        image_url = None
        if img_tag and img_tag.has_attr('src'):
            image_url = urljoin(self.config.base_url, img_tag['src'])
        
        # Extract description for additional details
        desc_p_tag = item_tag.select_one('p.m-0.truncate-two-lines, p.m-0.characteristics')
        description_text = extract_text_from_element(desc_p_tag) if desc_p_tag else ""
        
        # Parse year from description
        year = parse_year(description_text, full_title) if description_text else None
        
        # Parse box and papers status
        has_papers, has_box = parse_box_papers(description_text) if description_text else (None, None)
        
        # Parse case material from description using original logic
        case_material = None
        if description_text:
            # Try to find case material first (prioritize case over bezel)
            mat_search = re.search(
                r'\b(steel|stahl|gold|yellow-gold|white-gold|rose gold|titanium|platinum|nickel plated|rosegold|weissgold|gelbgold|edelstahl)\s+case\b', 
                description_text, re.IGNORECASE
            )
            
            # Fallback to any material mention if no case-specific material found
            if not mat_search:
                mat_search = re.search(
                    r'\b(steel|stahl|gold|yellow-gold|white-gold|rose gold|titanium|platinum|ceramic|nickel plated|rosegold|weissgold|gelbgold|edelstahl)\b', 
                    description_text, re.IGNORECASE
                )
            
            if mat_search:
                mat_text = mat_search.group(1).lower()
                if "stahl" in mat_text or "steel" in mat_text:
                    case_material = "Steel"
                elif "yellow-gold" in mat_text or "gelbgold" in mat_text:
                    case_material = "Yellow Gold"
                elif "white-gold" in mat_text or "weissgold" in mat_text:
                    case_material = "White Gold"
                elif "rose gold" in mat_text or "rosegold" in mat_text:
                    case_material = "Rose Gold"
                elif "gold" in mat_text:
                    case_material = "Gold"
                elif "titanium" in mat_text:
                    case_material = "Titanium"
                elif "platinum" in mat_text:
                    case_material = "Platinum"
                elif "ceramic" in mat_text:
                    case_material = "Ceramic"
                elif "nickel plated" in mat_text:
                    case_material = "Nickel"
                else:
                    case_material = mat_search.group(1).title()
        
        # Set condition based on description
        condition = parse_condition(description_text, self.config.key) if description_text else None
        
        # Create watch data
        return WatchData(
            title=full_title,
            url=url,
            site_name=self.config.name,
            site_key=self.config.key,
            brand=parsed_brand,
            model=parsed_model,
            reference=reference,
            year=year,
            price=price,
            currency="EUR",
            case_material=case_material,
            diameter=None,  # Original doesn't extract diameter from listing
            condition=condition,
            has_papers=has_papers,
            has_box=has_box,
            image_url=image_url
        )
    
    async def _extract_watch_details(self, watch: WatchData, soup: BeautifulSoup):
        """Extract additional details from World of Time detail page."""
        # The original implementation doesn't fetch detail pages for World of Time
        # All information comes from the listing page
        pass