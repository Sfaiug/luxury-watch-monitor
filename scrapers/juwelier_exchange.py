"""Juwelier Exchange scraper implementation."""

import re
from decimal import Decimal
from typing import List, Optional
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import json

from scrapers.base import BaseScraper
from models import WatchData
from utils import parse_year, parse_box_papers, parse_condition, extract_text_from_element


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
            # The widest picture of the srcset, a webp one where there is one;
            # without a srcset that names one, the plain src
            def rank(entry):
                src, *descriptor = entry.split()
                width = descriptor[0].rstrip("w") if descriptor else ""
                return (".webp" in src, int(width) if width.isdigit() else 0)

            entries = [entry for entry in img_tag.get('srcset', '').split(",") if entry.strip()]
            best_src = max(entries, key=rank).split()[0] if entries else img_tag.get('src')
            if best_src:
                image_url = urljoin(self.config.base_url, best_src)
        
        # The card's own data has the price to pay; the visible price block of a
        # reduced watch also holds the old price and the saving
        listed = json.loads(item_tag['data-product-information'])
        listed_price = listed.get('price')
        price = Decimal(str(listed_price)) if listed_price is not None else None
        
        # Made of price and address alone, as it was when the server learned the
        # former id it remembers the watch under
        watch = WatchData(
            title="Unknown Watch",
            url=url,
            site_name=self.config.name,
            site_key=self.config.key,
            price=price,
            currency="EUR",
            image_url=image_url
        )
        # The card names the watch, so its alert does too when the watch's own
        # page cannot be read; that page adds the rest
        if listed.get('name'):
            watch.title = listed['name']
            watch.brand = listed.get('brand')
            watch.model = self._model(watch.title, watch.brand)
        return watch
    
    @staticmethod
    def _model(title: str, brand: Optional[str]) -> Optional[str]:
        """The model as the watch's name gives it: what stands in quotes, else its first words."""
        if not brand:
            return None
        model_candidate = re.sub(r"^(Herrenuhr|Damenuhr|Unisexuhr)\s+", "", title, flags=re.IGNORECASE).strip()
        model_candidate = re.sub(fr"^{re.escape(brand)}\s*", "", model_candidate, flags=re.IGNORECASE).strip()
        
        quoted_model_match = re.search(r"'(.*?)'", model_candidate)
        if quoted_model_match and len(quoted_model_match.group(1).strip()) > 1:
            model = quoted_model_match.group(1).strip()
        else:  # Fallback: what comes before a reference, without common terms
            temp_model = re.sub(r"\s*\bRef\b.*$", "", model_candidate, flags=re.IGNORECASE)
            temp_model = re.sub(r'\s*(Automatik|Quarz|Chrono|GMT|Date)$', '', temp_model, flags=re.IGNORECASE).strip(" ,")
            model = " ".join(temp_model.split()[:3]).strip()
        
        if len(model) < 2 or model.lower() == brand.lower():
            return None
        return model
    
    async def _extract_watch_details(self, watch: WatchData, soup: BeautifulSoup):
        """Extract additional details from Juwelier Exchange detail page - matching original exactly."""
        
        # The watch has its name, brand and model from the listing card
        details = {
            "reference": None, "year": None,
            "condition_text": None, "case_material": None, "diameter": None,
            "box_status": None, "papers_status": None
        }
        
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
        
        if full_description_text:  # Parse from description text
            details["year"] = parse_year(full_description_text, watch.title)
            
            papers_status, box_status = parse_box_papers(full_description_text)
            details["papers_status"] = papers_status
            details["box_status"] = box_status
            
            # Diameter from description
            dia_match = re.search(r'(?:Durchmesser|Gehäusedurchmesser|Gehäusegröße):?\s*(?:von|ca\.)?\s*(\d{1,2}(?:[,.]\d{1,2})?)\s*mm', full_description_text, re.IGNORECASE)
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
        
        # Update watch object with extracted details
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