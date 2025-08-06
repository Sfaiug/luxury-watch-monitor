"""Juwelier Exchange scraper implementation."""

import re
from typing import List, Optional
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import json

from scrapers.base import BaseScraper
from models import WatchData
from utils import parse_price, parse_year, parse_box_papers, parse_condition, extract_text_from_element


class JuwelierExchangeScraper(BaseScraper):
    """Scraper for Juwelier Exchange website."""
    
    async def _extract_watches(self, soup: BeautifulSoup) -> List[WatchData]:
        """Extract watches from Juwelier Exchange listing page."""
        watches = []
        
        # Use exact selectors from original implementation
        watch_elements = soup.select('div.card.product-box[data-product-information]')
        
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
        link_tag = item_tag.select_one('a.card-body-link')
        if not (link_tag and link_tag.has_attr('href')):
            return None
        
        url = urljoin(self.config.base_url, link_tag['href'])
        
        # Extract image URL with srcset logic from original
        image_url = None
        img_tag = item_tag.select_one('img.product-image')
        if img_tag:
            # Simplified srcset logic from original
            srcset = img_tag.get('srcset', '')
            if srcset:
                # Prefer higher resolution webp, then jpg, then src
                potential_srcs = [s.strip().split(" ")[0] for s in srcset.split(",")]
                best_src = img_tag.get('src', '')  # fallback to src
                for res in ["1920x1920.webp", "800x800.webp", "400x400.webp", ".webp"]:  # Order of preference
                    for p_src in potential_srcs:
                        if res in p_src:
                            best_src = p_src
                            break
                    if res in best_src:
                        break  # Found preferred type
                image_url = urljoin(self.config.base_url, best_src)
            elif img_tag.has_attr('src'):
                image_url = urljoin(self.config.base_url, img_tag['src'])
        
        # Get price from listing first
        price_tag_listing = item_tag.select_one('span.product-price')
        price = None
        if price_tag_listing:
            price_text_raw_listing = extract_text_from_element(price_tag_listing)
            if price_text_raw_listing:
                price = parse_price(price_text_raw_listing, "EUR")
        
        # Create initial watch data - details will be filled from detail page
        return WatchData(
            title="Unknown Watch",  # Will be updated from detail page
            url=url,
            site_name=self.config.name,
            site_key=self.config.key,
            price=price,
            currency="EUR",
            image_url=image_url
        )
    
    async def _extract_watch_details(self, watch: WatchData, soup: BeautifulSoup):
        """Extract additional details from Juwelier Exchange detail page - matching original exactly."""
        
        # Initialize details dict like original
        details = {
            "brand": None, "model": None, "reference": None, "year": None, 
            "condition_text": None, "case_material": None, "diameter": None, 
            "box_status": None, "papers_status": None, "description_main": None, "title": None
        }
        
        # Parse JSON-LD Data first (original logic)
        json_ld_script = soup.find("script", type="application/ld+json", string=re.compile(r'"@type": "Product"'))
        if json_ld_script:
            try:
                json_data = json.loads(json_ld_script.string)
                if json_data.get("name"):
                    details["title"] = json_data["name"]
                if json_data.get("brand", {}).get("name"):
                    details["brand"] = json_data["brand"]["name"]
                if json_data.get("description"):
                    details["description_main"] = json_data["description"]
            except Exception as e:
                self.logger.error(f"Error parsing JSON-LD for Juwelier Exchange: {e}")
        
        # Override/Supplement with visible elements if JSON-LD is incomplete
        title_tag = soup.select_one('h1.product-detail-name')
        if title_tag and (details["title"] is None or not details["title"]):
            details["title"] = extract_text_from_element(title_tag)
        
        # Properties Table
        properties_table = soup.select_one('table.product-detail-properties-table')
        if properties_table:
            for row in properties_table.find_all('tr', class_='properties-row'):
                label_tag = row.find('th', class_='properties-label')
                value_tag = row.find('td', class_='properties-value')
                if label_tag and value_tag:
                    label = extract_text_from_element(label_tag).lower().replace(":", "")
                    value = extract_text_from_element(value_tag)
                    
                    if "artikelnummer" == label and (details["reference"] is None or not details["reference"]):
                        details["reference"] = value
                    elif "marke" == label and (details["brand"] is None or not details["brand"]):
                        details["brand"] = value
                    elif "zustand" == label and (details["condition_text"] is None or not details["condition_text"]):
                        details["condition_text"] = value
                    elif "art der legierung" == label:
                        details["case_material"] = value
                    elif "legierung" == label and value.isdigit() and details.get("case_material"):
                        details["case_material"] = f"{value} {details.get('case_material', '')}".strip()  # e.g., "750 Gold"
                    elif "material" == label and (details["case_material"] is None or not details["case_material"]):  # Broader material
                        details["case_material"] = value
        
        # Main Description (for year, box/papers, diameter, richer condition)
        description_div = soup.select_one('div.product-detail-description-text[itemprop="description"]')
        full_description_text = ""
        if description_div:
            full_description_text = extract_text_from_element(description_div, separator=" ")
            if details["description_main"] is None or not details["description_main"]:  # Use if JSON-LD desc was empty
                details["description_main"] = full_description_text
        
        if full_description_text:  # Parse from description text
            details["year"] = parse_year(full_description_text, details["title"] or "")
            
            papers_status, box_status = parse_box_papers(full_description_text)
            details["papers_status"] = papers_status
            details["box_status"] = box_status
            
            # Diameter from description
            dia_match = re.search(r'(?:Durchmesser|Gehäusedurchmesser|Gehäusegröße)\s*(?:von|ca\.)?\s*(\d{1,2}(?:[,.]\d{1,2})?)\s*mm', full_description_text, re.IGNORECASE)
            if dia_match:
                details["diameter"] = dia_match.group(1).replace(',', '.') + " mm"
            else:  # Check for format like "20,5 x 28 mm" for rectangular cases (take first dimension)
                dia_match_rect = re.search(r'(\d{1,2}(?:[,.]\d{1,2})?)\s*x\s*\d{1,2}(?:[,.]\d{1,2})?\s*mm', full_description_text, re.IGNORECASE)
                if dia_match_rect:
                    details["diameter"] = dia_match_rect.group(1).replace(',', '.') + " mm"
            
            # Case material from description if not found in table
            if details["case_material"] is None:
                mat_match = re.search(r'(?:Gehäuse aus |Material: |aus |Kaliber\s+\d+\s+)\b(Stahl|Edelstahl|Gold|Gelbgold|Weißgold|Rotgold|Roségold|Titan|Keramik|Silber(?:,\s*vergoldet)?|PVD-Beschichtung|Rosévergoldung|750er Gold|333er Gold|925er Silber)\b', full_description_text, re.IGNORECASE)
                if mat_match:
                    mat_text_raw = mat_match.group(1)
                    mat_text = mat_text_raw.lower()
                    if "stahl" in mat_text or "edelstahl" in mat_text:
                        details["case_material"] = "Steel"
                    elif "gelbgold" in mat_text or ("750er gold" in mat_text and "gelb" in mat_text_raw.lower()):
                        details["case_material"] = "Yellow Gold"
                    elif "weißgold" in mat_text:
                        details["case_material"] = "White Gold"
                    elif "rotgold" in mat_text or "roségold" in mat_text or "rosévergoldung" in mat_text:
                        details["case_material"] = "Rose Gold"
                    elif "gold" in mat_text:
                        details["case_material"] = "Gold"
                    elif "titan" in mat_text:
                        details["case_material"] = "Titanium"
                    elif "keramik" in mat_text:
                        details["case_material"] = "Ceramic"
                    elif "silber" in mat_text:
                        details["case_material"] = "Silver" if "925er" in mat_text_raw else mat_text_raw.title()
                    elif "pvd" in mat_text:
                        details["case_material"] = "PVD Coated Steel"
                    else:
                        details["case_material"] = mat_text_raw.title()
        
        # Refine model extraction from title
        if details["brand"] and details["title"]:
            model_candidate = details["title"]
            model_candidate = re.sub(r"^(Herrenuhr|Damenuhr|Unisexuhr)\s+", "", model_candidate, flags=re.IGNORECASE).strip()
            model_candidate = re.sub(fr"^{re.escape(details['brand'])}\s*", "", model_candidate, flags=re.IGNORECASE).strip()
            
            # Try to extract from single quotes
            quoted_model_match = re.search(r"'(.*?)'", model_candidate)
            if quoted_model_match and len(quoted_model_match.group(1).strip()) > 1:
                details["model"] = quoted_model_match.group(1).strip()
            else:  # Fallback: remove reference and common terms
                temp_model = model_candidate
                if details.get("reference") and details["reference"] in temp_model:
                    temp_model = temp_model.replace(details["reference"], "").strip(" |,-")
                temp_model = re.sub(r'\s*(Automatik|Quarz|Chrono|GMT|Date)$', '', temp_model, flags=re.IGNORECASE).strip(" ,")
                details["model"] = " ".join(temp_model.split()[:3]).strip() if temp_model else None
            
            if not details["model"] or details["model"].lower() == details["brand"].lower() or len(details["model"]) < 2:
                details["model"] = None
        
        # Update watch object with extracted details
        if details["title"]:
            watch.title = details["title"]
        if details["brand"]:
            watch.brand = details["brand"]
        if details["model"]:
            watch.model = details["model"]
        if details["reference"]:
            watch.reference = details["reference"]
        if details["year"]:
            watch.year = details["year"]
        if details["case_material"]:
            watch.case_material = details["case_material"]
        if details["diameter"]:
            watch.diameter = details["diameter"]
        if details["condition_text"]:
            watch.condition = parse_condition(details["condition_text"], self.config.key)
        if details["papers_status"] is not None:
            watch.has_papers = details["papers_status"]
        if details["box_status"] is not None:
            watch.has_box = details["box_status"]