"""Online component discovery and dynamic footprint creation.

Allows the AI agent to use ANY component -- not just the built-in library.
When the AI references a component not in the local footprint library, this
module creates a best-effort footprint from package specifications.

Supported flows:
1. AI generates DSL code referencing an unknown footprint name
2. The DSL builder calls ``discover_footprint(name)``
3. This module maps the name to a standard package and creates a Footprint

Common package families:
- SOT-23, SOT-223, SOT-89, SOT-363, SOT-563
- SOIC-8/14/16, TSSOP-8/14/16/20, MSOP-8/10
- QFP-32/44/48/64/100, QFN-16/20/24/32/48
- 0201/0402/0603/0805/1206 (metric & imperial)
- DIP-8/14/16/20/28/40
- TO-220, TO-252/DPAK, TO-263/D2PAK
"""

from __future__ import annotations

import re
from typing import Optional

from ..core.datatypes import Point, PadShape, PadType, Layer
from ..core.component import Footprint, Pad, SilkLine
from .footprints import FOOTPRINT_REGISTRY, get_footprint


# ── Package specification database ──────────────────────────────────────────

_PACKAGE_SPECS: dict[str, dict] = {
    # SMD passives (metric naming)
    "0201": {"pads": 2, "sx": 0.3, "sy": 0.3, "pitch": 0.5, "type": "passive"},
    "0402": {"pads": 2, "sx": 0.5, "sy": 0.5, "pitch": 0.8, "type": "passive"},
    "0603": {"pads": 2, "sx": 0.8, "sy": 0.8, "pitch": 1.2, "type": "passive"},
    "0805": {"pads": 2, "sx": 1.0, "sy": 1.0, "pitch": 1.6, "type": "passive"},
    "1206": {"pads": 2, "sx": 1.2, "sy": 1.2, "pitch": 2.4, "type": "passive"},
    "1210": {"pads": 2, "sx": 1.2, "sy": 1.5, "pitch": 2.4, "type": "passive"},
    "2010": {"pads": 2, "sx": 1.5, "sy": 1.5, "pitch": 3.8, "type": "passive"},
    "2512": {"pads": 2, "sx": 1.8, "sy": 1.8, "pitch": 5.0, "type": "passive"},
    # SOT family
    "SOT-23": {"pads": 3, "type": "sot"},
    "SOT-23-3": {"pads": 3, "type": "sot"},
    "SOT-23-5": {"pads": 5, "type": "sot5"},
    "SOT-23-6": {"pads": 6, "type": "sot6"},
    "SOT-223": {"pads": 3, "type": "sot223"},
    "SOT-89": {"pads": 3, "type": "sot89"},
    "SOT-363": {"pads": 6, "type": "sot363"},
    # SOIC family
    "SOIC-8": {"pads": 8, "pitch": 1.27, "type": "soic"},
    "SOIC-14": {"pads": 14, "pitch": 1.27, "type": "soic"},
    "SOIC-16": {"pads": 16, "pitch": 1.27, "type": "soic"},
    "SOIC-18": {"pads": 18, "pitch": 1.27, "type": "soic"},
    "SOIC-20": {"pads": 20, "pitch": 1.27, "type": "soic"},
    "SOIC-24": {"pads": 24, "pitch": 1.27, "type": "soic"},
    "SOIC-28": {"pads": 28, "pitch": 1.27, "type": "soic"},
    # TSSOP family
    "TSSOP-8": {"pads": 8, "pitch": 0.65, "type": "tssop"},
    "TSSOP-10": {"pads": 10, "pitch": 0.65, "type": "tssop"},
    "TSSOP-14": {"pads": 14, "pitch": 0.65, "type": "tssop"},
    "TSSOP-16": {"pads": 16, "pitch": 0.65, "type": "tssop"},
    "TSSOP-20": {"pads": 20, "pitch": 0.65, "type": "tssop"},
    "TSSOP-24": {"pads": 24, "pitch": 0.65, "type": "tssop"},
    "TSSOP-28": {"pads": 28, "pitch": 0.65, "type": "tssop"},
    # MSOP
    "MSOP-8": {"pads": 8, "pitch": 0.65, "type": "msop"},
    "MSOP-10": {"pads": 10, "pitch": 0.5, "type": "msop"},
    # QFP family
    "QFP-32": {"pads": 32, "pitch": 0.8, "type": "qfp"},
    "QFP-44": {"pads": 44, "pitch": 0.8, "type": "qfp"},
    "QFP-48": {"pads": 48, "pitch": 0.5, "type": "qfp"},
    "QFP-64": {"pads": 64, "pitch": 0.5, "type": "qfp"},
    "QFP-100": {"pads": 100, "pitch": 0.5, "type": "qfp"},
    "LQFP-32": {"pads": 32, "pitch": 0.8, "type": "qfp"},
    "LQFP-48": {"pads": 48, "pitch": 0.5, "type": "qfp"},
    "LQFP-64": {"pads": 64, "pitch": 0.5, "type": "qfp"},
    "LQFP-100": {"pads": 100, "pitch": 0.5, "type": "qfp"},
    "TQFP-32": {"pads": 32, "pitch": 0.8, "type": "qfp"},
    "TQFP-44": {"pads": 44, "pitch": 0.8, "type": "qfp"},
    "TQFP-48": {"pads": 48, "pitch": 0.5, "type": "qfp"},
    "TQFP-64": {"pads": 64, "pitch": 0.5, "type": "qfp"},
    # QFN family
    "QFN-8": {"pads": 8, "pitch": 0.65, "type": "qfn", "body": 3.0},
    "QFN-16": {"pads": 16, "pitch": 0.65, "type": "qfn", "body": 3.0},
    "QFN-20": {"pads": 20, "pitch": 0.5, "type": "qfn", "body": 4.0},
    "QFN-24": {"pads": 24, "pitch": 0.5, "type": "qfn", "body": 4.0},
    "QFN-28": {"pads": 28, "pitch": 0.5, "type": "qfn", "body": 5.0},
    "QFN-32": {"pads": 32, "pitch": 0.5, "type": "qfn", "body": 5.0},
    "QFN-40": {"pads": 40, "pitch": 0.5, "type": "qfn", "body": 6.0},
    "QFN-48": {"pads": 48, "pitch": 0.5, "type": "qfn", "body": 7.0},
    "QFN-56": {"pads": 56, "pitch": 0.4, "type": "qfn", "body": 7.0},
    # DIP family
    "DIP-8": {"pads": 8, "pitch": 2.54, "row_pitch": 7.62, "type": "dip"},
    "DIP-14": {"pads": 14, "pitch": 2.54, "row_pitch": 7.62, "type": "dip"},
    "DIP-16": {"pads": 16, "pitch": 2.54, "row_pitch": 7.62, "type": "dip"},
    "DIP-20": {"pads": 20, "pitch": 2.54, "row_pitch": 7.62, "type": "dip"},
    "DIP-28": {"pads": 28, "pitch": 2.54, "row_pitch": 7.62, "type": "dip"},
    "DIP-40": {"pads": 40, "pitch": 2.54, "row_pitch": 15.24, "type": "dip"},
    # Power packages
    "TO-220": {"pads": 3, "type": "to220"},
    "TO-220-3": {"pads": 3, "type": "to220"},
    "TO-252": {"pads": 3, "type": "dpak"},
    "DPAK": {"pads": 3, "type": "dpak"},
    "TO-263": {"pads": 3, "type": "d2pak"},
    "D2PAK": {"pads": 3, "type": "d2pak"},
    # DFN small packages
    "DFN-8": {"pads": 8, "pitch": 0.5, "type": "qfn", "body": 3.0},
    # BGA family (for ARM SoCs, DDR, etc.)
    "BGA-64": {"pads": 64, "pitch": 0.8, "type": "bga", "body": 8.0, "rows": 8, "cols": 8},
    "BGA-100": {"pads": 100, "pitch": 0.8, "type": "bga", "body": 10.0, "rows": 10, "cols": 10},
    "BGA-144": {"pads": 144, "pitch": 0.8, "type": "bga", "body": 12.0, "rows": 12, "cols": 12},
    "BGA-169": {"pads": 169, "pitch": 0.8, "type": "bga", "body": 13.0, "rows": 13, "cols": 13},
    "BGA-196": {"pads": 196, "pitch": 0.8, "type": "bga", "body": 14.0, "rows": 14, "cols": 14},
    "BGA-256": {"pads": 256, "pitch": 0.8, "type": "bga", "body": 17.0, "rows": 16, "cols": 16},
    "BGA-324": {"pads": 324, "pitch": 0.65, "type": "bga", "body": 15.0, "rows": 18, "cols": 18},
    "BGA-400": {"pads": 400, "pitch": 0.65, "type": "bga", "body": 17.0, "rows": 20, "cols": 20},
    "UFBGA-169": {"pads": 169, "pitch": 0.5, "type": "bga", "body": 7.0, "rows": 13, "cols": 13},
    "UFBGA-201": {"pads": 201, "pitch": 0.5, "type": "bga", "body": 8.0, "rows": 15, "cols": 15},
    "WLCSP-25": {"pads": 25, "pitch": 0.4, "type": "bga", "body": 2.5, "rows": 5, "cols": 5},
    "WLCSP-36": {"pads": 36, "pitch": 0.4, "type": "bga", "body": 3.0, "rows": 6, "cols": 6},
    # TSOP for DDR memory
    "TSOP-54": {"pads": 54, "pitch": 0.5, "type": "tssop"},
    "TSOP-66": {"pads": 66, "pitch": 0.5, "type": "tssop"},
    # WSON (for flash memory)
    "WSON-8": {"pads": 8, "pitch": 1.27, "type": "qfn", "body": 5.0},
    # LQFP larger pin counts
    "LQFP-100": {"pads": 100, "pitch": 0.5, "type": "qfp"},
    "LQFP-144": {"pads": 144, "pitch": 0.5, "type": "qfp"},
    "LQFP-176": {"pads": 176, "pitch": 0.5, "type": "qfp"},
    "LQFP-208": {"pads": 208, "pitch": 0.5, "type": "qfp"},
    # QFN larger pin counts
    "QFN-64": {"pads": 64, "pitch": 0.4, "type": "qfn", "body": 9.0},
    "QFN-68": {"pads": 68, "pitch": 0.4, "type": "qfn", "body": 9.0},
    "QFN-72": {"pads": 72, "pitch": 0.4, "type": "qfn", "body": 10.0},
}

# Map common component names to known packages
_COMPONENT_PACKAGE_MAP: dict[str, str] = {
    # Voltage regulators
    "AMS1117": "SOT-223", "LM1117": "SOT-223",
    "LM7805": "TO-220", "LM7812": "TO-220",
    "AP2112": "SOT-23-5", "MCP1700": "SOT-23",
    "RT9080": "SOT-23-5", "XC6206": "SOT-23",
    "HT7333": "SOT-89", "SPX3819": "SOT-23-5",
    "TPS7A05": "SOT-23-5",
    # Op-amps
    "LM358": "SOIC-8", "LM324": "SOIC-14",
    "OPA2134": "SOIC-8", "TL072": "SOIC-8", "NE5532": "SOIC-8",
    # Communication ICs
    "MAX485": "SOIC-8", "MAX232": "SOIC-16", "MAX3232": "SOIC-16",
    "CH340": "SOIC-16", "CP2102": "QFN-24", "FT232R": "SOIC-28",
    # Motor drivers
    "DRV8833": "SOIC-8", "L293D": "DIP-16", "L298N": "DIP-20",
    "A4988": "QFN-24", "TMC2209": "QFN-28", "TB6612": "SOIC-24",
    # ADCs/DACs
    "ADS1115": "TSSOP-10", "MCP3008": "DIP-16", "MCP4725": "SOT-23-6",
    # Sensors (ICs)
    "BME280": "QFN-8", "BMP280": "QFN-8",
    "MPU6050": "QFN-24", "MPU9250": "QFN-24",
    "INA219": "SOT-23-5", "INA226": "TSSOP-10",
    "SHT30": "DFN-8", "MAX6675": "SOIC-8", "HX711": "SOIC-16",
    # Power MOSFETs
    "IRF540N": "TO-220", "IRLZ44N": "TO-220",
    "AO3400": "SOT-23", "SI2302": "SOT-23",
    "2N7002": "SOT-23", "BSS138": "SOT-23",
    # Audio
    "MAX98357": "QFN-16", "PAM8403": "SOIC-16",
    # Memory
    "W25Q32": "SOIC-8", "W25Q64": "SOIC-8", "W25Q128": "SOIC-8",
    "AT24C256": "SOIC-8",
    # MCUs not already in library
    "ATMEGA328P": "DIP-28", "ATTINY85": "DIP-8",
    "ATTINY13": "SOIC-8", "STM32F103C8": "LQFP-48",
    "STM32F401": "LQFP-64", "RP2040": "QFN-56", "SAMD21": "QFP-48",
    # ARM application processors
    "STM32MP157": "BGA-196", "STM32MP153": "BGA-196",
    "STM32MP151": "BGA-196", "STM32H7": "LQFP-144",
    "STM32F4": "LQFP-100", "STM32F7": "LQFP-144",
    "STM32L4": "LQFP-64", "STM32G4": "LQFP-48",
    "IMX6ULL": "BGA-289", "IMX8M": "BGA-400",
    "ALLWINNER": "BGA-256", "RK3328": "BGA-256",
    "RK3399": "BGA-400", "AM3358": "BGA-324",
    "NRF52840": "QFN-48", "NRF52832": "QFN-48",
    "ESP32S3": "QFN-56", "ESP32C3": "QFN-32",
    # DDR memory
    "MT41K256M16": "TSOP-54", "MT41K512M16": "TSOP-54",
    "AS4C256M16": "TSOP-54", "K4B4G1646": "TSOP-54",
    # SPI NOR flash
    "S25FL127": "WSON-8", "W25Q256": "SOIC-8",
    "MX25L128": "SOIC-8", "IS25LP256": "SOIC-8",
    # eMMC
    "THGBMJG6C1LBAIL": "BGA-100",
    # Ethernet PHY
    "LAN8720": "QFN-24", "KSZ8081": "QFN-24",
    "DP83848": "QFP-48", "RTL8211": "QFN-48",
    # USB PD controllers
    "STUSB4500": "QFN-24", "FUSB302": "QFN-16",
    "CYPD3177": "QFN-24",
    # Power regulators (switching)
    "TPS54620": "QFN-24", "TPS62172": "WLCSP-36",
    "TPS65217": "QFN-48", "AXP209": "QFN-48",
    "TLV70033": "SOT-23-5", "MCP130": "SOT-23",
    # LED drivers
    "WS2811": "SOIC-8", "TLC5940": "DIP-28", "PCA9685": "TSSOP-28",
    # Misc
    "NE555": "SOIC-8", "CD4017": "SOIC-16",
    "74HC595": "SOIC-16", "74HC165": "SOIC-16",
    "74HC245": "SOIC-20", "ULN2003": "SOIC-16",
}


def _make_pad(number: str, pos: Point, sx: float, sy: float,
              shape: PadShape = PadShape.RECT, drill: float = 0.0) -> Pad:
    """Helper to create a Pad with correct PadType."""
    pad_type = PadType.THT if drill > 0 else PadType.SMD
    layers = [Layer.F_CU, Layer.B_CU] if drill > 0 else [Layer.F_CU]
    return Pad(
        number=number,
        pad_type=pad_type,
        shape=shape,
        position=pos,
        size_x=sx,
        size_y=sy,
        drill_size=drill,
        layers=layers,
    )


def discover_footprint(name: str) -> Optional[Footprint]:
    """Try to create or find a footprint for an arbitrary component name.

    Resolution order:
    1. Exact match in built-in footprint library
    2. Package name match (e.g. "SOIC-8", "QFP-48")
    3. Component-to-package mapping (e.g. "NE555" -> SOIC-8)
    4. Regex pattern matching for common naming conventions
    5. Return None if nothing works

    Any successfully created footprint is cached in the global registry
    so subsequent lookups are instant.
    """
    # 1. Check built-in library first
    existing = get_footprint(name)
    if existing is not None:
        return existing

    # Normalize the name for matching
    name_upper = name.upper().strip()
    name_clean = re.sub(r"[_\s]+", "-", name_upper)

    # 2. Direct package spec match
    fp = _try_package_spec(name_clean)
    if fp is not None:
        _register(name, fp)
        return fp

    # 3. Component-to-package mapping
    for comp_name, pkg_name in _COMPONENT_PACKAGE_MAP.items():
        if comp_name in name_upper:
            fp = _try_package_spec(pkg_name)
            if fp is not None:
                # Create with original name but mapped package pads
                fp_named = Footprint(
                    name=name,
                    pads=fp.pads,
                    silk_lines=fp.silk_lines,
                    silk_circles=fp.silk_circles,
                    courtyard=fp.courtyard,
                )
                _register(name, fp_named)
                return fp_named

    # 4. Pattern matching for common conventions
    fp = _try_pattern_match(name_clean)
    if fp is not None:
        _register(name, fp)
        return fp

    return None


def _register(name: str, fp: Footprint) -> None:
    """Cache a discovered footprint in the global registry."""
    # Wrap the Footprint in a factory lambda for the registry format
    FOOTPRINT_REGISTRY[name] = lambda _fp=fp: _fp


def _try_package_spec(name: str) -> Optional[Footprint]:
    """Create a footprint from a known package specification."""
    spec = _PACKAGE_SPECS.get(name)
    if spec is None:
        # Try inserting a dash (e.g. "SOIC8" -> "SOIC-8")
        name_dash = re.sub(r"(\D)(\d)", r"\1-\2", name)
        spec = _PACKAGE_SPECS.get(name_dash)
    if spec is None:
        return None

    pkg_type = spec["type"]

    if pkg_type == "passive":
        return _make_passive_fp(name, spec)
    elif pkg_type in ("sot", "sot5", "sot6", "sot223", "sot89", "sot363"):
        return _make_sot_fp(name, spec)
    elif pkg_type in ("soic", "tssop", "msop"):
        return _make_dual_row_fp(name, spec)
    elif pkg_type == "qfp":
        return _make_qfp_fp(name, spec)
    elif pkg_type == "qfn":
        return _make_qfn_fp(name, spec)
    elif pkg_type == "dip":
        return _make_dip_fp(name, spec)
    elif pkg_type in ("to220", "dpak", "d2pak"):
        return _make_power_fp(name, spec)
    elif pkg_type == "bga":
        return _make_bga_fp(name, spec)

    return None


def _try_pattern_match(name: str) -> Optional[Footprint]:
    """Try regex patterns to identify package type from name."""
    # Match "R_0603", "C_0402", "L_0805" etc.
    m = re.match(r"^[RCL][-_]?(\d{4})$", name)
    if m:
        size = m.group(1)
        spec = _PACKAGE_SPECS.get(size)
        if spec:
            return _make_passive_fp(name, spec)

    # Match "SOIC-N", "TSSOP-N", "MSOP-N", "SOP-N"
    m = re.match(r"^(SOIC|TSSOP|MSOP|SOP)[-_]?(\d+)$", name)
    if m:
        pkg_family = m.group(1)
        n = int(m.group(2))
        pkg = f"{pkg_family}-{n}"
        spec = _PACKAGE_SPECS.get(pkg)
        if spec is None:
            # Auto-generate specs for any dual-row pin count
            pitch = 1.27 if pkg_family == "SOIC" else 0.65
            body_w = max(3.9, n * pitch / 4)
            spec = {"pads": n, "pitch": pitch, "type": "dual",
                    "body_w": body_w, "span": 6.0 if pkg_family == "SOIC" else 4.4}
        return _make_dual_row_fp(name, spec)

    # Match "QFP-N", "LQFP-N", "TQFP-N"
    m = re.match(r"^[LT]?QFP[-_]?(\d+)$", name)
    if m:
        n = int(m.group(1))
        spec = _PACKAGE_SPECS.get(f"QFP-{n}")
        if spec is None:
            # Auto-generate specs for any QFP pin count
            import math
            pins_per_side = max(2, n // 4)
            pitch = 0.8 if n <= 48 else (0.5 if n <= 100 else 0.4)
            body = max(7.0, math.ceil(pins_per_side * pitch + 2.0))
            spec = {"pads": n, "pitch": pitch, "type": "qfp", "body": body}
        return _make_qfp_fp(name, spec)

    # Match "QFN-N", "DFN-N"
    m = re.match(r"^[D]?QFN[-_]?(\d+)$", name)
    if not m:
        m = re.match(r"^DFN[-_]?(\d+)$", name)
    if m:
        n = int(m.group(1))
        spec = _PACKAGE_SPECS.get(f"QFN-{n}")
        if spec is None:
            # Auto-generate specs for any QFN pin count
            import math
            pins_per_side = max(2, n // 4)
            pitch = 0.65 if n <= 16 else (0.5 if n <= 48 else 0.4)
            body = max(3.0, math.ceil(pins_per_side * pitch + 1.0))
            spec = {"pads": n, "pitch": pitch, "type": "qfn", "body": body}
        return _make_qfn_fp(name, spec)

    # Match "DIP-N"
    m = re.match(r"^DIP[-_]?(\d+)$", name)
    if m:
        n = int(m.group(1))
        spec = _PACKAGE_SPECS.get(f"DIP-{n}")
        if spec:
            return _make_dip_fp(name, spec)

    # Match "SOT-23-N" or "SOT23"
    m = re.match(r"^SOT[-_]?23[-_]?(\d)?$", name)
    if m:
        n = int(m.group(1)) if m.group(1) else 3
        pkg = f"SOT-23-{n}" if n > 3 else "SOT-23"
        spec = _PACKAGE_SPECS.get(pkg)
        if spec:
            return _make_sot_fp(name, spec)

    # Match "BGA-N", "UFBGA-N", "WLCSP-N"
    m = re.match(r"^(?:UF)?BGA[-_]?(\d+)$", name)
    if m:
        n = int(m.group(1))
        spec = _PACKAGE_SPECS.get(f"BGA-{n}")
        if spec is None:
            spec = _PACKAGE_SPECS.get(f"UFBGA-{n}")
        if spec:
            return _make_bga_fp(name, spec)
    m = re.match(r"^WLCSP[-_]?(\d+)$", name)
    if m:
        n = int(m.group(1))
        spec = _PACKAGE_SPECS.get(f"WLCSP-{n}")
        if spec:
            return _make_bga_fp(name, spec)

    # Match "LQFP-N" for larger pin counts
    m = re.match(r"^LQFP[-_]?(\d+)$", name)
    if m:
        n = int(m.group(1))
        spec = _PACKAGE_SPECS.get(f"LQFP-{n}")
        if spec:
            return _make_qfp_fp(name, spec)

    # Match "TSOP-N"
    m = re.match(r"^TSOP[-_]?(\d+)$", name)
    if m:
        n = int(m.group(1))
        spec = _PACKAGE_SPECS.get(f"TSOP-{n}")
        if spec:
            return _make_dual_row_fp(name, spec)

    return None


# ── Footprint Generators ───────────────────────────────────────────────────

def _make_passive_fp(name: str, spec: dict) -> Footprint:
    """Create a 2-pad passive component footprint."""
    sx = spec["sx"]
    sy = spec["sy"]
    pitch = spec["pitch"]
    half = pitch / 2
    return Footprint(
        name=name,
        pads=[
            _make_pad("1", Point(-half, 0), sx, sy, PadShape.RECT),
            _make_pad("2", Point(half, 0), sx, sy, PadShape.RECT),
        ],
        silk_lines=[
            SilkLine(Point(-pitch / 2 - 0.2, -sy / 2 - 0.2),
                     Point(pitch / 2 + 0.2, -sy / 2 - 0.2)),
            SilkLine(Point(-pitch / 2 - 0.2, sy / 2 + 0.2),
                     Point(pitch / 2 + 0.2, sy / 2 + 0.2)),
        ],
    )


def _make_sot_fp(name: str, spec: dict) -> Footprint:
    """Create SOT-23 family footprints."""
    n = spec["pads"]

    if n == 3:
        pads = [
            _make_pad("1", Point(-0.95, 1.1), 0.6, 0.7),
            _make_pad("2", Point(0.95, 1.1), 0.6, 0.7),
            _make_pad("3", Point(0, -1.1), 0.6, 0.7),
        ]
    elif n == 5:
        pads = [
            _make_pad("1", Point(-0.95, 1.1), 0.6, 0.7),
            _make_pad("2", Point(0, 1.1), 0.6, 0.7),
            _make_pad("3", Point(0.95, 1.1), 0.6, 0.7),
            _make_pad("4", Point(0.95, -1.1), 0.6, 0.7),
            _make_pad("5", Point(-0.95, -1.1), 0.6, 0.7),
        ]
    elif n == 6:
        pads = [
            _make_pad("1", Point(-0.95, 1.1), 0.6, 0.7),
            _make_pad("2", Point(0, 1.1), 0.6, 0.7),
            _make_pad("3", Point(0.95, 1.1), 0.6, 0.7),
            _make_pad("4", Point(0.95, -1.1), 0.6, 0.7),
            _make_pad("5", Point(0, -1.1), 0.6, 0.7),
            _make_pad("6", Point(-0.95, -1.1), 0.6, 0.7),
        ]
    else:
        pads = [
            _make_pad(str(i + 1),
                      Point(-0.95 + i * 0.95, 1.1 if i < n // 2 else -1.1),
                      0.6, 0.7)
            for i in range(n)
        ]

    return Footprint(
        name=name, pads=pads,
        silk_lines=[
            SilkLine(Point(-1.5, -1.5), Point(1.5, -1.5)),
            SilkLine(Point(1.5, -1.5), Point(1.5, 1.5)),
            SilkLine(Point(1.5, 1.5), Point(-1.5, 1.5)),
            SilkLine(Point(-1.5, 1.5), Point(-1.5, -1.5)),
        ],
    )


def _make_dual_row_fp(name: str, spec: dict) -> Footprint:
    """Create SOIC/TSSOP/MSOP dual-row IC footprints."""
    n = spec["pads"]
    pitch = spec["pitch"]
    half_n = n // 2

    pkg_type = spec["type"]
    if pkg_type == "soic":
        row_spacing = 5.4 if n <= 8 else 7.5
        pad_w, pad_h = 0.6, 1.5
    elif pkg_type == "tssop":
        row_spacing = 4.4 if n <= 8 else 6.4
        pad_w, pad_h = 0.4, 1.2
    else:  # msop
        row_spacing = 3.0
        pad_w, pad_h = 0.4, 1.0

    half_row = row_spacing / 2
    pads = []
    for i in range(half_n):
        y_offset = (i - (half_n - 1) / 2) * pitch
        pads.append(_make_pad(str(i + 1), Point(-half_row, y_offset), pad_w, pad_h))
        pads.append(_make_pad(str(n - i), Point(half_row, y_offset), pad_w, pad_h))

    body_h = (half_n - 1) * pitch + 2.0
    body_w = row_spacing - 1.0
    silks = [
        SilkLine(Point(-body_w / 2, -body_h / 2), Point(body_w / 2, -body_h / 2)),
        SilkLine(Point(body_w / 2, -body_h / 2), Point(body_w / 2, body_h / 2)),
        SilkLine(Point(body_w / 2, body_h / 2), Point(-body_w / 2, body_h / 2)),
        SilkLine(Point(-body_w / 2, body_h / 2), Point(-body_w / 2, -body_h / 2)),
    ]
    return Footprint(name=name, pads=pads, silk_lines=silks)


def _make_qfp_fp(name: str, spec: dict) -> Footprint:
    """Create QFP/LQFP/TQFP footprints."""
    n = spec["pads"]
    pitch = spec["pitch"]
    per_side = n // 4
    body = per_side * pitch + 2.0
    half_body = body / 2
    pad_extend = half_body + 2.0
    pad_w, pad_h = 0.3, 1.5

    pads = []
    for i in range(per_side):
        x = (i - (per_side - 1) / 2) * pitch
        pads.append(_make_pad(str(i + 1), Point(x, pad_extend), pad_w, pad_h))
    for i in range(per_side):
        y = (i - (per_side - 1) / 2) * pitch
        pads.append(_make_pad(str(per_side + i + 1), Point(pad_extend, y), pad_h, pad_w))
    for i in range(per_side):
        x = ((per_side - 1) / 2 - i) * pitch
        pads.append(_make_pad(str(2 * per_side + i + 1), Point(x, -pad_extend), pad_w, pad_h))
    for i in range(per_side):
        y = ((per_side - 1) / 2 - i) * pitch
        pads.append(_make_pad(str(3 * per_side + i + 1), Point(-pad_extend, y), pad_h, pad_w))

    silks = [
        SilkLine(Point(-half_body, -half_body), Point(half_body, -half_body)),
        SilkLine(Point(half_body, -half_body), Point(half_body, half_body)),
        SilkLine(Point(half_body, half_body), Point(-half_body, half_body)),
        SilkLine(Point(-half_body, half_body), Point(-half_body, -half_body)),
    ]
    return Footprint(name=name, pads=pads, silk_lines=silks)


def _make_qfn_fp(name: str, spec: dict) -> Footprint:
    """Create QFN footprints with exposed pad."""
    n = spec["pads"]
    pitch = spec["pitch"]
    body = spec.get("body", 5.0)
    per_side = n // 4
    half_body = body / 2
    pad_w, pad_h = 0.3, 0.8

    pads = []
    for i in range(per_side):
        x = (i - (per_side - 1) / 2) * pitch
        pads.append(_make_pad(str(i + 1), Point(x, half_body), pad_w, pad_h))
    for i in range(per_side):
        y = (i - (per_side - 1) / 2) * pitch
        pads.append(_make_pad(str(per_side + i + 1), Point(half_body, y), pad_h, pad_w))
    for i in range(per_side):
        x = ((per_side - 1) / 2 - i) * pitch
        pads.append(_make_pad(str(2 * per_side + i + 1), Point(x, -half_body), pad_w, pad_h))
    for i in range(per_side):
        y = ((per_side - 1) / 2 - i) * pitch
        pads.append(_make_pad(str(3 * per_side + i + 1), Point(-half_body, y), pad_h, pad_w))

    # Exposed thermal pad
    ep_size = body * 0.5
    pads.append(_make_pad(str(n + 1), Point(0, 0), ep_size, ep_size))

    silks = [
        SilkLine(Point(-half_body, -half_body), Point(half_body, -half_body)),
        SilkLine(Point(half_body, -half_body), Point(half_body, half_body)),
        SilkLine(Point(half_body, half_body), Point(-half_body, half_body)),
        SilkLine(Point(-half_body, half_body), Point(-half_body, -half_body)),
    ]
    return Footprint(name=name, pads=pads, silk_lines=silks)


def _make_dip_fp(name: str, spec: dict) -> Footprint:
    """Create DIP through-hole footprints."""
    n = spec["pads"]
    pitch = spec["pitch"]
    row_pitch = spec["row_pitch"]
    half_n = n // 2
    half_row = row_pitch / 2

    pads = []
    for i in range(half_n):
        y = (i - (half_n - 1) / 2) * pitch
        pads.append(_make_pad(str(i + 1), Point(-half_row, y), 1.6, 1.6,
                              PadShape.CIRCLE, drill=0.8))
        pads.append(_make_pad(str(n - i), Point(half_row, y), 1.6, 1.6,
                              PadShape.CIRCLE, drill=0.8))

    body_h = (half_n - 1) * pitch + 2.0
    body_w = row_pitch - 1.0
    silks = [
        SilkLine(Point(-body_w / 2, -body_h / 2), Point(body_w / 2, -body_h / 2)),
        SilkLine(Point(body_w / 2, -body_h / 2), Point(body_w / 2, body_h / 2)),
        SilkLine(Point(body_w / 2, body_h / 2), Point(-body_w / 2, body_h / 2)),
        SilkLine(Point(-body_w / 2, body_h / 2), Point(-body_w / 2, -body_h / 2)),
    ]
    return Footprint(name=name, pads=pads, silk_lines=silks)


def _make_power_fp(name: str, spec: dict) -> Footprint:
    """Create TO-220/DPAK/D2PAK footprints."""
    pkg_type = spec["type"]

    if pkg_type == "to220":
        pads = [
            _make_pad("1", Point(-2.54, 0), 1.6, 1.6, PadShape.CIRCLE, drill=0.8),
            _make_pad("2", Point(0, 0), 1.6, 1.6, PadShape.CIRCLE, drill=0.8),
            _make_pad("3", Point(2.54, 0), 1.6, 1.6, PadShape.CIRCLE, drill=0.8),
        ]
        silks = [
            SilkLine(Point(-5, -3), Point(5, -3)),
            SilkLine(Point(5, -3), Point(5, 5)),
            SilkLine(Point(5, 5), Point(-5, 5)),
            SilkLine(Point(-5, 5), Point(-5, -3)),
        ]
    elif pkg_type == "dpak":
        pads = [
            _make_pad("1", Point(-2.3, 3.5), 1.0, 1.5),
            _make_pad("2", Point(0, -1.5), 6.0, 6.0),  # tab/drain
            _make_pad("3", Point(2.3, 3.5), 1.0, 1.5),
        ]
        silks = [
            SilkLine(Point(-3.5, -4.5), Point(3.5, -4.5)),
            SilkLine(Point(3.5, -4.5), Point(3.5, 4.5)),
            SilkLine(Point(3.5, 4.5), Point(-3.5, 4.5)),
            SilkLine(Point(-3.5, 4.5), Point(-3.5, -4.5)),
        ]
    else:  # d2pak
        pads = [
            _make_pad("1", Point(-2.54, 5.0), 1.2, 2.0),
            _make_pad("2", Point(0, -2.0), 8.0, 8.0),
            _make_pad("3", Point(2.54, 5.0), 1.2, 2.0),
        ]
        silks = [
            SilkLine(Point(-5, -6), Point(5, -6)),
            SilkLine(Point(5, -6), Point(5, 6)),
            SilkLine(Point(5, 6), Point(-5, 6)),
            SilkLine(Point(-5, 6), Point(-5, -6)),
        ]
    return Footprint(name=name, pads=pads, silk_lines=silks)


def _make_bga_fp(name: str, spec: dict) -> Footprint:
    """Create BGA (Ball Grid Array) footprints for SoCs, DDR, etc."""
    n = spec["pads"]
    pitch = spec["pitch"]
    body = spec.get("body", 10.0)
    rows = spec.get("rows", int(n ** 0.5))
    cols = spec.get("cols", int(n ** 0.5))
    half_body = body / 2
    pad_d = pitch * 0.45  # ball diameter ~45% of pitch

    # BGA ball naming: rows = A, B, C, ... columns = 1, 2, 3, ...
    row_labels = []
    for i in range(rows):
        if i < 26:
            row_labels.append(chr(ord('A') + i))
        else:
            row_labels.append(chr(ord('A') + i // 26 - 1) + chr(ord('A') + i % 26))

    pads = []
    ball_num = 1
    for r in range(rows):
        for c in range(cols):
            if ball_num > n:
                break
            x = (c - (cols - 1) / 2) * pitch
            y = (r - (rows - 1) / 2) * pitch
            pad_name = f"{row_labels[r]}{c + 1}"
            pads.append(_make_pad(pad_name, Point(x, y), pad_d, pad_d, PadShape.CIRCLE))
            ball_num += 1

    silks = [
        SilkLine(Point(-half_body, -half_body), Point(half_body, -half_body)),
        SilkLine(Point(half_body, -half_body), Point(half_body, half_body)),
        SilkLine(Point(half_body, half_body), Point(-half_body, half_body)),
        SilkLine(Point(-half_body, half_body), Point(-half_body, -half_body)),
        # Pin A1 marker
        SilkLine(Point(-half_body + 0.5, -half_body), Point(-half_body, -half_body + 0.5)),
    ]
    return Footprint(name=name, pads=pads, silk_lines=silks)


def list_discoverable_packages() -> str:
    """Return a formatted string of all discoverable package types for LLM prompts."""
    lines = ["Dynamically supported packages (use any of these as footprint names):"]
    for pkg_name in sorted(_PACKAGE_SPECS.keys()):
        spec = _PACKAGE_SPECS[pkg_name]
        lines.append(f"  {pkg_name}: {spec['pads']} pins ({spec['type']})")
    lines.append("")
    lines.append("Known component-to-package mappings (use component name as footprint):")
    for comp, pkg in sorted(_COMPONENT_PACKAGE_MAP.items()):
        lines.append(f"  {comp} -> {pkg}")
    return "\n".join(lines)
