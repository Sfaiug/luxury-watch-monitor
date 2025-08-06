"""Watch Out scraper implementation."""

import re
import json
from typing import List, Optional
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from scrapers.base import BaseScraper
from models import WatchData
from utils import parse_price, parse_year, parse_box_papers, parse_condition, extract_text_from_element


class WatchOutScraper(BaseScraper):
    """Scraper for Watch Out website."""
    
    async def _extract_watches(self, soup: BeautifulSoup) -> List[WatchData]:
        """Extract watches from Watch Out listing page."""
        watches = []
        
        # First extract Shopify analytics data
        shopify_products_data = []
        try:
            script_tag_analytics = soup.find("script", string=re.compile(r"window\.ShopifyAnalytics\.meta"))
            if script_tag_analytics and script_tag_analytics.string:
                match = re.search(r"var meta = (\{.*?\})\s*;", script_tag_analytics.string, re.DOTALL)
                if match:
                    meta_json_str = match.group(1)
                    meta_data = json.loads(meta_json_str)
                    if "products" in meta_data:
                        shopify_products_data = meta_data["products"]
                        self.logger.info(f"Found {len(shopify_products_data)} items in Watch Out ShopifyAnalytics data.")
                else:
                    self.logger.warning("Could not find 'var meta = {...}' in ShopifyAnalytics script for Watch Out.")
            else:
                self.logger.warning("Could not find ShopifyAnalytics script tag for Watch Out.")
        except Exception as e:
            self.logger.error(f"Error parsing Watch Out ShopifyAnalytics data: {e}")
        
        # Use exact selectors from original implementation
        product_card_elements = soup.select('product-card')
        
        for idx, card_element in enumerate(product_card_elements):
            try:
                watch = self._parse_watch_element(card_element, idx, shopify_products_data)
                if watch:
                    watches.append(watch)
            except Exception as e:
                self.logger.error(f"Error parsing watch element: {e}")
        
        return watches
    
    def _parse_watch_element(self, card_element, idx: int, shopify_products_data: list) -> Optional[WatchData]:
        """Parse a single watch element from listing page - matching original logic exactly."""
        
        # Skip sold out items
        if card_element.select_one('sold-out-badge'):
            return None
        
        # Extract URL and handle
        handle = card_element.get('handle')
        url = None
        
        if handle:
            url = urljoin(self.config.base_url, f"/products/{handle}")
        else:
            link_tag_in_card = card_element.select_one('a[href*="/products/"]')
            if link_tag_in_card and link_tag_in_card.has_attr('href'):
                path = link_tag_in_card['href']
                url = urljoin(self.config.base_url, path)
                if path.startswith("/products/"):
                    handle = path.split("/products/")[-1].split("?")[0]
            else:
                return None
        
        # Initialize watch data
        watch_data = {
            "brand": None, "model": None, "reference": None, "year": None,
            "price": None, "title": None, "image_url": None
        }
        
        # Get card title
        card_title_tag = card_element.select_one('.product-card__title a.bold')
        card_title_text = extract_text_from_element(card_title_tag) if card_title_tag else None
        
        # Match with Shopify analytics data
        shopify_item = None
        if idx < len(shopify_products_data):
            temp_shopify_item = shopify_products_data[idx]
            temp_shopify_title_variant = (temp_shopify_item.get("variants")[0].get("name") 
                                        if temp_shopify_item.get("variants") else None)
            temp_shopify_title_product = temp_shopify_item.get("untranslatedTitle", 
                                                             temp_shopify_item.get("title"))
            shopify_item_title = (temp_shopify_title_variant 
                                if temp_shopify_title_variant and temp_shopify_title_variant.lower() != "default title" 
                                else temp_shopify_title_product)
            
            analytics_prod_url_part = (temp_shopify_item.get("variants")[0].get("product", {}).get("url", "") 
                                     if temp_shopify_item.get("variants") 
                                     else temp_shopify_item.get("url", ""))
            
            # Match by handle in URL or title similarity
            if handle and analytics_prod_url_part and handle in analytics_prod_url_part:
                shopify_item = temp_shopify_item
            elif (card_title_text and shopify_item_title and 
                  card_title_text.lower() in shopify_item_title.lower()):
                shopify_item = temp_shopify_item
            elif not analytics_prod_url_part and not card_title_text:
                shopify_item = temp_shopify_item
        
        # Extract data from Shopify analytics
        if shopify_item:
            watch_data["brand"] = shopify_item.get("vendor") if shopify_item.get("vendor") else None
            variant = shopify_item.get("variants")[0] if shopify_item.get("variants") else {}
            
            # Prefer variant name, but fall back to untranslatedTitle if variant name is "Default Title"
            variant_name = variant.get("name")
            if variant_name and variant_name.lower() != "default title":
                watch_data["title"] = variant_name
            else:
                # Fall back to untranslatedTitle, then title
                title_candidate = shopify_item.get("untranslatedTitle", shopify_item.get("title"))
                if title_candidate:
                    watch_data["title"] = title_candidate
            
            price_cents = variant.get("price")
            if price_cents is not None:
                watch_data["price"] = price_cents / 100.0  # Convert from cents to EUR
            
            sku_ref = variant.get("sku")
            if sku_ref:
                watch_data["reference"] = sku_ref
        
        # Fallback to visual elements if analytics data missing
        if not watch_data["title"] and card_title_text:
            watch_data["title"] = card_title_text
        
        brand_tag_visual = card_element.select_one('.product-card__info a.text-xs.link-faded')
        if brand_tag_visual and not watch_data["brand"]:
            watch_data["brand"] = extract_text_from_element(brand_tag_visual)
        
        if not watch_data["price"]:
            price_tag_visual = card_element.select_one('sale-price')
            if price_tag_visual:
                price_text_raw = extract_text_from_element(price_tag_visual)
                if price_text_raw:
                    watch_data["price"] = parse_price(price_text_raw, "EUR")
        
        # Extract reference from badge
        ref_badge = card_element.select_one('.product-card__badge-list span.badge--primary')
        if ref_badge and not watch_data["reference"]:
            ref_text = extract_text_from_element(ref_badge)
            if ref_text:
                watch_data["reference"] = ref_text
        
        # Extract image URL
        img_tag_visual = card_element.select_one('img.product-card__image')
        if img_tag_visual:
            src_val = img_tag_visual.get('srcset')
            if src_val:
                img_parts = [s.strip().split(" ")[0] for s in src_val.split(",")]
                watch_data["image_url"] = urljoin(self.config.base_url, 
                                                img_parts[-1] if img_parts else (img_tag_visual.get('src') or ""))
            elif img_tag_visual.get('src'):
                watch_data["image_url"] = urljoin(self.config.base_url, img_tag_visual.get('src'))
        
        # Create watch data
        return WatchData(
            title=watch_data["title"] or "Unknown Watch",
            url=url,
            site_name=self.config.name,
            site_key=self.config.key,
            brand=watch_data["brand"],
            model=watch_data["model"],
            reference=watch_data["reference"],
            year=watch_data["year"],
            price=watch_data["price"],
            currency="EUR",
            image_url=watch_data["image_url"]
        )
    
    async def _extract_watch_details(self, watch: WatchData, soup: BeautifulSoup):
        """Extract additional details from Watch Out detail page - matching original exactly."""
        
        # Extract main description
        main_desc_area = soup.select_one('div.section-stack__intro div.metafield-rich_text_field div.prose')
        main_desc_text = extract_text_from_element(main_desc_area, separator=" ") if main_desc_area else ""
        
        # Parse accordion details
        accordion_box = soup.select_one('div.accordion-box')
        accordion_data = self._parse_accordion_details_watch_out(accordion_box)
        
        # Extract details from accordion data (original logic)
        if accordion_data.get("herstellungsjahr"):
            watch.year = parse_year(accordion_data["herstellungsjahr"], watch.title or "")
        
        if accordion_data.get("referenznummer"):
            watch.reference = accordion_data["referenznummer"]
        
        if accordion_data.get("durchmesser"):
            dia_text = accordion_data["durchmesser"]
            dia_match = re.search(r'(\d{1,2}(?:[.,]\d{1,2})?)\s*mm', dia_text, re.IGNORECASE)
            if dia_match:
                watch.diameter = dia_match.group(1).replace(",", ".") + "mm"
            else:
                watch.diameter = dia_text
        
        if accordion_data.get("gehäusematerial"):
            watch.case_material = accordion_data["gehäusematerial"]
        
        # Parse box and papers from full description
        full_description = main_desc_text + " " + " ".join(accordion_data.values())
        has_papers, has_box = parse_box_papers(full_description)
        if has_papers is not None:
            watch.has_papers = has_papers
        if has_box is not None:
            watch.has_box = has_box
        
        # Set condition
        watch.condition = parse_condition(full_description, self.config.key)
    
    def _parse_accordion_details_watch_out(self, accordion_box) -> dict:
        """Parse accordion details from Watch Out - matching original helper function."""
        parsed_details = {}
        
        if not accordion_box:
            return parsed_details
        
        try:
            for collapsible in accordion_box.select('collapsible-element'):
                summary_elem = collapsible.select_one('summary')
                if not summary_elem:
                    continue
                
                summary_text = extract_text_from_element(summary_elem).lower().strip()
                
                # Get content from the collapsible
                content_area = collapsible.select_one('div[id]')  # The collapsible content
                if not content_area:
                    continue
                
                content_text = extract_text_from_element(content_area)
                
                # Map to fields based on summary text
                if "spezifikationen" in summary_text or "details" in summary_text:
                    # Parse key-value pairs from specifications
                    lines = content_text.split('\n')
                    current_key = None
                    
                    for line in lines:
                        line = line.strip()
                        if ':' in line:
                            key, value = line.split(':', 1)
                            key = key.strip().lower()
                            value = value.strip()
                            
                            if "herstellungsjahr" in key or "jahr" in key:
                                parsed_details["herstellungsjahr"] = value
                            elif "referenz" in key:
                                parsed_details["referenznummer"] = value
                            elif "durchmesser" in key:
                                parsed_details["durchmesser"] = value
                            elif "gehäusematerial" in key or "material" in key:
                                parsed_details["gehäusematerial"] = value
                            elif "zustand" in key or "condition" in key:
                                parsed_details["zustand"] = value
                        elif current_key and line:
                            # Continuation of previous value
                            if current_key in parsed_details:
                                parsed_details[current_key] += " " + line
                
                elif "zustand" in summary_text or "condition" in summary_text:
                    parsed_details["zustand"] = content_text
                
                elif "lieferumfang" in summary_text or "scope" in summary_text:
                    parsed_details["lieferumfang"] = content_text
        
        except Exception as e:
            self.logger.warning(f"Error parsing accordion details: {e}")
        
        return parsed_details