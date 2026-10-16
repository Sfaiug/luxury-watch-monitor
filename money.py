"""Price parsing shared by configuration and listings."""

import re
from decimal import Decimal, InvalidOperation
from typing import Optional


def parse_price(price_text: str, currency: str = "EUR") -> Optional[Decimal]:
    """
    Parse price from various text formats.

    Args:
        price_text: Raw price text
        currency: Expected currency

    Returns:
        Decimal price or None if parsing fails
    """
    if not price_text:
        return None

    # Handle "price on request" cases
    if re.search(r"price.*on.*request|preis.*auf.*anfrage", price_text, re.IGNORECASE):
        return None

    # Clean the price string
    cleaned = price_text

    # Remove currency symbols and text
    cleaned = re.sub(r"[€$£¥₹CHF\s]|EUR|USD|GBP|CHF", "", cleaned, flags=re.IGNORECASE)

    # Remove a trailing "no cents" dash: 8.500,- or 6,250.-
    cleaned = re.sub(r"[.,]-+$", "", cleaned)

    # Handle different decimal/thousand separators
    if "." in cleaned and "," in cleaned:
        # Determine which is decimal separator based on position
        if cleaned.rfind(".") < cleaned.rfind(","):
            # European format: 1.234,56
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            # US format: 1,234.56
            cleaned = cleaned.replace(",", "")
    else:
        separator = "," if "," in cleaned else "."
        parts = cleaned.split(separator)
        if (
            len(parts) > 1
            and parts[0].isdigit()
            and all(len(part) == 3 for part in parts[1:])
        ):
            # Thousands separator: 1,234 or 1.234.567
            cleaned = "".join(parts)
        else:
            # Decimal separator: 1234,56
            cleaned = cleaned.replace(",", ".")

    # Try to convert to Decimal
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None
