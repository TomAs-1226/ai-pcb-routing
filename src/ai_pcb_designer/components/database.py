"""Component database with online lookup via LCSC/JLCPCB parts API.

Provides access to millions of real-world electronic components with:
- Manufacturer part numbers (MPN)
- Footprint specifications
- Pricing and stock availability
- Datasheet links

Falls back to a built-in offline database for common components when
network is unavailable.
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .footprints import get_footprint, FOOTPRINT_REGISTRY


@dataclass
class ComponentInfo:
    """Information about an electronic component."""
    lcsc_part: str = ""           # e.g., "C14663"
    mpn: str = ""                 # Manufacturer Part Number
    manufacturer: str = ""
    description: str = ""
    package: str = ""             # e.g., "0603", "SOT-23-3"
    category: str = ""
    value: str = ""
    footprint_name: str = ""      # Maps to our footprint library
    datasheet_url: str = ""
    price: float = 0.0            # USD per unit (approximate)
    stock: int = 0
    attributes: dict[str, str] = field(default_factory=dict)


# ─── Built-in Offline Database ──────────────────────────────────────────────

BUILTIN_COMPONENTS: dict[str, ComponentInfo] = {
    # Resistors
    "10k_0603": ComponentInfo(
        lcsc_part="C25804",
        mpn="0603WAF1002T5E",
        manufacturer="UNI-ROYAL",
        description="10kΩ ±1% 1/10W 0603 resistor",
        package="0603",
        category="Resistors",
        value="10k",
        footprint_name="R_0603",
        price=0.001,
        stock=999999,
    ),
    "1k_0603": ComponentInfo(
        lcsc_part="C21190",
        mpn="0603WAF1001T5E",
        manufacturer="UNI-ROYAL",
        description="1kΩ ±1% 1/10W 0603 resistor",
        package="0603",
        category="Resistors",
        value="1k",
        footprint_name="R_0603",
        price=0.001,
        stock=999999,
    ),
    "4.7k_0603": ComponentInfo(
        lcsc_part="C23162",
        mpn="0603WAF4701T5E",
        manufacturer="UNI-ROYAL",
        description="4.7kΩ ±1% 1/10W 0603 resistor",
        package="0603",
        category="Resistors",
        value="4.7k",
        footprint_name="R_0603",
        price=0.001,
        stock=999999,
    ),
    "330_0805": ComponentInfo(
        lcsc_part="C17630",
        mpn="0805W8F3300T5E",
        manufacturer="UNI-ROYAL",
        description="330Ω ±1% 1/8W 0805 resistor",
        package="0805",
        category="Resistors",
        value="330",
        footprint_name="R_0805",
        price=0.001,
        stock=999999,
    ),
    # Capacitors
    "100nF_0603": ComponentInfo(
        lcsc_part="C14663",
        mpn="CL10B104KB8NNNL",
        manufacturer="Samsung Electro-Mechanics",
        description="100nF ±10% 50V X7R 0603 capacitor",
        package="0603",
        category="Capacitors",
        value="100nF",
        footprint_name="C_0603",
        price=0.002,
        stock=999999,
    ),
    "10uF_0805": ComponentInfo(
        lcsc_part="C15850",
        mpn="CL21A106KAYNNNE",
        manufacturer="Samsung Electro-Mechanics",
        description="10µF ±10% 25V X5R 0805 capacitor",
        package="0805",
        category="Capacitors",
        value="10uF",
        footprint_name="C_0805",
        price=0.005,
        stock=999999,
    ),
    # LEDs
    "LED_Green_0603": ComponentInfo(
        lcsc_part="C72043",
        mpn="19-217/GHC-YR1S2/3T",
        manufacturer="Everlight",
        description="Green LED 0603 20mA",
        package="0603",
        category="LEDs",
        value="LED_Green",
        footprint_name="LED_0603",
        price=0.01,
        stock=999999,
    ),
    "LED_Red_0805": ComponentInfo(
        lcsc_part="C84256",
        mpn="19-217/R6C-AL1M2VY/3T",
        manufacturer="Everlight",
        description="Red LED 0805 20mA",
        package="0805",
        category="LEDs",
        value="LED_Red",
        footprint_name="LED_0805",
        price=0.01,
        stock=999999,
    ),
    # Voltage Regulators
    "AMS1117-3.3": ComponentInfo(
        lcsc_part="C6186",
        mpn="AMS1117-3.3",
        manufacturer="AMS",
        description="3.3V 1A LDO linear regulator SOT-223",
        package="SOT-223",
        category="Voltage Regulators",
        value="AMS1117-3.3",
        footprint_name="SOT-223",
        price=0.05,
        stock=999999,
    ),
    # ESP32
    "ESP32-WROOM-32E": ComponentInfo(
        lcsc_part="C701342",
        mpn="ESP32-WROOM-32E(M113EH3200PH3Q0)",
        manufacturer="Espressif",
        description="ESP32 WiFi+BT module, 4MB flash",
        package="ESP32-WROOM-32",
        category="Modules",
        value="ESP32-WROOM-32",
        footprint_name="ESP32-WROOM-32",
        price=2.50,
        stock=999999,
    ),
}


class ComponentDatabase:
    """Component database with online lookup and offline fallback.

    Searches LCSC parts database via their public API for real
    components with pricing, stock, and specifications.
    """

    LCSC_SEARCH_URL = "https://wmsc.lcsc.com/ftps/wm/search/global"
    USER_AGENT = "AI-PCB-Designer/0.1"

    def __init__(self) -> None:
        self._cache: dict[str, list[ComponentInfo]] = {}
        self._offline_mode = False

    def search(self, query: str, limit: int = 10) -> list[ComponentInfo]:
        """Search for components by description, MPN, or value.

        Tries online LCSC API first, falls back to built-in database.
        """
        cache_key = f"{query}:{limit}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        results = []

        # Try online search first
        if not self._offline_mode:
            try:
                results = self._search_lcsc(query, limit)
            except Exception:
                self._offline_mode = True

        # Fallback to built-in database
        if not results:
            results = self._search_builtin(query, limit)

        self._cache[cache_key] = results
        return results

    def get_by_lcsc_part(self, lcsc_part: str) -> ComponentInfo | None:
        """Look up a specific LCSC part number."""
        for comp in BUILTIN_COMPONENTS.values():
            if comp.lcsc_part == lcsc_part:
                return comp
        return None

    def get_by_mpn(self, mpn: str) -> ComponentInfo | None:
        """Look up by manufacturer part number."""
        for comp in BUILTIN_COMPONENTS.values():
            if comp.mpn.lower() == mpn.lower():
                return comp
        # Try online
        results = self.search(mpn, limit=1)
        return results[0] if results else None

    def _search_lcsc(self, query: str, limit: int) -> list[ComponentInfo]:
        """Search LCSC parts API."""
        params = json.dumps({
            "keyword": query,
            "limit": limit,
            "currentPage": 1,
        }).encode("utf-8")

        req = urllib.request.Request(
            self.LCSC_SEARCH_URL,
            data=params,
            headers={
                "Content-Type": "application/json",
                "User-Agent": self.USER_AGENT,
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        results = []
        products = data.get("result", {}).get("tipProductDetailUrlVOList") or []

        for product in products[:limit]:
            comp = ComponentInfo(
                lcsc_part=product.get("productCode", ""),
                mpn=product.get("productModel", ""),
                manufacturer=product.get("brandNameEn", ""),
                description=product.get("productIntroEn", ""),
                package=product.get("encapStandard", ""),
                category=product.get("parentCatalogName", ""),
                price=self._extract_price(product),
                stock=product.get("stockNumber", 0),
                datasheet_url=product.get("pdfUrl", ""),
            )
            comp.footprint_name = self._map_package_to_footprint(comp.package)
            results.append(comp)

        return results

    def _search_builtin(self, query: str, limit: int) -> list[ComponentInfo]:
        """Search the built-in offline database."""
        query_lower = query.lower()
        matches = []
        for key, comp in BUILTIN_COMPONENTS.items():
            score = 0
            if query_lower in key.lower():
                score += 10
            if query_lower in comp.mpn.lower():
                score += 8
            if query_lower in comp.description.lower():
                score += 5
            if query_lower in comp.value.lower():
                score += 7
            if query_lower in comp.category.lower():
                score += 3
            if score > 0:
                matches.append((score, comp))

        matches.sort(key=lambda x: x[0], reverse=True)
        return [comp for _, comp in matches[:limit]]

    @staticmethod
    def _extract_price(product: dict) -> float:
        """Extract price from LCSC product data."""
        prices = product.get("productPriceList", [])
        if prices:
            try:
                return float(prices[0].get("productPrice", 0))
            except (ValueError, IndexError):
                pass
        return 0.0

    @staticmethod
    def _map_package_to_footprint(package: str) -> str:
        """Map LCSC package names to our footprint library names."""
        package_map = {
            "0402": "R_0402",
            "0603": "R_0603",
            "0805": "R_0805",
            "SOT-23": "SOT-23-3",
            "SOT-23-3": "SOT-23-3",
            "SOT-223": "SOT-223",
            "SOT-223-3": "SOT-223",
        }
        return package_map.get(package, "")

    def list_categories(self) -> list[str]:
        """List available component categories."""
        cats = set()
        for comp in BUILTIN_COMPONENTS.values():
            cats.add(comp.category)
        return sorted(cats)
