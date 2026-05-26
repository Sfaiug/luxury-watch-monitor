"""Large MUV model-selection regression corpus."""

from unittest.mock import patch

import pytest

from muv_service import MUVActionService


def _case(
    expected_brand,
    expected_model,
    reference,
    *,
    listing_brand=None,
    listing_model=None,
    title=None,
):
    brand = listing_brand or expected_brand
    model = listing_model or f"{expected_model} {reference}".strip()
    listing_title = title or f"{brand} {model}".strip()
    return {
        "brand": brand,
        "model": model,
        "title": listing_title,
        "expected_brand": expected_brand,
        "expected_model": expected_model,
    }


MUV_MAPPING_CASES = [
    _case("Rolex", "Daytona", "116500LN"),
    _case("Rolex", "Submariner", "116610LN", listing_model="Submariner Date"),
    _case("Rolex", "GMT-Master II", "126710BLRO"),
    _case("Rolex", "GMT-Master", "16700"),
    _case("Rolex", "Datejust", "126334"),
    _case("Rolex", "Day-Date", "228238"),
    _case("Rolex", "Oyster Perpetual", "124300"),
    _case("Rolex", "Yacht-Master", "126622"),
    _case("Rolex", "Yacht-Master II", "116680"),
    _case("Rolex", "Explorer", "124270"),
    _case("Rolex", "Explorer II", "226570"),
    _case("Rolex", "Sea-Dweller", "126600"),
    _case("Rolex", "Sky-Dweller", "326934"),
    _case("Rolex", "Milgauss", "116400GV"),
    _case("Rolex", "Air King", "126900"),
    _case("Rolex", "Cellini", "50535"),
    _case("Rolex", "Lady Datejust", "279173"),
    _case("Rolex", "Date", "15200"),
    _case("Rolex", "Oysterquartz", "17000"),
    _case("Rolex", "Precision", "6426"),
    _case("Patek Philippe", "Nautilus", "5711/1A-010"),
    _case("Patek Philippe", "Aquanaut", "5167A-001"),
    _case("Patek Philippe", "Calatrava", "5196G-001"),
    _case("Patek Philippe", "Golden Ellipse", "3738/100J"),
    _case("Patek Philippe", "Annual Calendar", "5205G"),
    _case("Patek Philippe", "Perpetual Calendar", "3940J"),
    _case("Patek Philippe", "Worldtime", "5130P"),
    _case("Patek Philippe", "Travel Time", "5524G"),
    _case("Patek Philippe", "Gondolo", "5124G"),
    _case("Patek Philippe", "Twenty 4", "4910/10A"),
    _case("Audemars Piguet", "Royal Oak", "15500ST"),
    _case("Audemars Piguet", "Code 11.59", "15210OR"),
    _case("Audemars Piguet", "Millenary", "4101"),
    _case("Audemars Piguet", "Jules Audemars Chronograph", "26391OR"),
    _case("Audemars Piguet", "Edward Piguet", "25925BA"),
    _case("Audemars Piguet", "Carnegie", "limited edition"),
    _case("Audemars Piguet", "Ultra Thin Vintage", "1970s"),
    _case("Audemars Piguet", "Huitieme", "chronograph"),
    _case("Omega", "Seamaster", "210.30.42.20.03.001"),
    _case("Omega", "Speedmaster", "3510.50"),
    _case("Omega", "Speedmaster Moonwatch", "310.30.42.50.01.002"),
    _case("Omega", "Moonwatch", "Professional 145.022"),
    _case("Omega", "Constellation", "Globemaster"),
    _case("Omega", "De Ville", "Prestige"),
    _case("Omega", "Railmaster", "220.10.40.20.01.001"),
    _case("Omega", "Flightmaster", "145.036"),
    _case("Omega", "Speedmaster Racing", "326.30.40.50.01.001"),
    _case("Omega", "Speedmaster Date", "3513.50"),
    _case("Cartier", "Tank", "Must XL"),
    _case("Cartier", "Santos", "WSSA0029"),
    _case("Cartier", "Santos 100", "W20073X8"),
    _case("Cartier", "Santos Dumont", "W2SA0011"),
    _case("Cartier", "Ballon Bleu de Cartier", "WSBB0049"),
    _case("Cartier", "Roadster", "W62020X6"),
    _case("Cartier", "Ronde", "Solo"),
    _case("Cartier", "Tank Solo", "WSTA0028"),
    _case("Cartier", "Calibre de Cartier", "W7100016"),
    _case("Cartier", "Tortue", "WA501009"),
    _case("Breitling", "Colt", "A17380"),
    _case("Breitling", "Avenger II", "GMT A32390"),
    _case("Breitling", "Avenger Skyland", "A13380"),
    _case("Breitling", "Superocean", "A17367"),
    _case("Breitling", "Colt GMT", "A32350"),
    _case("Breitling", "Superocean Chronograph II", "A13341"),
    _case("Breitling", "Chronomat 41", "AB0140"),
    _case("Breitling", "Montbrillant", "Datora"),
    _case("Breitling", "Navitimer Heritage", "A13324"),
    _case("IWC", "Portugieser", "IW500705"),
    _case("IWC", "Big Pilot", "IW501001"),
    _case("IWC", "Mark XVIII", "IW327009"),
    _case("IWC", "Portofino", "IW356501"),
    _case("IWC", "Ingenieur", "IW323902"),
    _case("IWC", "Aquatimer", "IW329001"),
    _case("IWC", "Da Vinci", "IW356601"),
    _case("IWC", "Mark XX", "IW328201"),
    _case("Tudor", "Pelagos", "25600TN"),
    _case("Tudor", "Heritage Black Bay", "79230N"),
    _case("Tudor", "Black Bay 41", "79540"),
    _case("Tudor", "Black Bay", "58 79030N"),
    _case("Tudor", "Black Bay 36", "79500"),
    _case("Tudor", "Submariner", "79090"),
    _case("Tudor", "Ranger", "79950"),
    _case("Tudor", "Royal", "M28600"),
    _case("Panerai", "Luminor", "PAM00112"),
    _case("Panerai", "Luminor GMT", "PAM00088"),
    _case("Panerai", "Luminor Marina", "PAM00111"),
    _case("Panerai", "Radiomir", "PAM00210"),
    _case("Panerai", "Submersible", "PAM00683"),
    _case(
        "A. Lange & Söhne",
        "Lange 1",
        "191.032",
        listing_brand="A Lange Sohne",
    ),
    _case("A. Lange & Söhne", "Datograph", "403.035"),
    _case("Zenith", "El Primero", "Chronomaster"),
    _case("Hublot", "Big Bang", "301.SX.130.RX"),
    _case("Hublot", "Classic Fusion", "511.NX.1171.RX"),
    _case(
        "Vacheron & Constantin",
        "Overseas",
        "4500V",
        listing_brand="Vacheron Constantin",
    ),
    _case("Tag Heuer", "Carrera", "CBK221B"),
    _case("Tag Heuer", "Monaco", "CAW211P"),
    _case(
        "Jaeger LeCoultre",
        "Reverso",
        "Q3858522",
        listing_brand="Jaeger-LeCoultre",
    ),
    _case("Blancpain", "Fifty Fathoms", "5015"),
    _case("Breguet", "Type XX", "3800ST"),
    _case("Bvlgari", "Octo", "Finissimo", listing_brand="Bulgari"),
]


def _muv_whitelist_from_cases():
    whitelist = []
    seen = set()
    for index, case in enumerate(MUV_MAPPING_CASES, start=1):
        key = (case["expected_brand"], case["expected_model"])
        if key in seen:
            continue
        seen.add(key)
        whitelist.append(
            {
                "BrandName": case["expected_brand"],
                "BrandId": index,
                "ModelName": case["expected_model"],
                "ModelId": index * 10,
                "RefMP": 1,
            }
        )
    return whitelist


assert len(MUV_MAPPING_CASES) == 100


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    MUV_MAPPING_CASES,
    ids=lambda case: f"{case['brand']} {case['model']}",
)
async def test_muv_selects_expected_model_for_past_listing_style_corpus(
    mock_logger, case
):
    service = MUVActionService(None, None, mock_logger)
    service._whitelist = _muv_whitelist_from_cases()

    with patch("muv_service.APP_CONFIG") as mock_config:
        mock_config.muv_match_threshold = 0.72

        match = await service.match_listing(
            {
                "brand": case["brand"],
                "model": case["model"],
                "title": case["title"],
            }
        )

    assert match is not None
    assert match.brand_name == case["expected_brand"]
    assert match.model_name == case["expected_model"]
