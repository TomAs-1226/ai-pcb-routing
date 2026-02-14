"""Catalog lookup — search and filter real components for AI design.

The AI agent calls these functions to find suitable parts for a design.
Results are formatted as text that can be injected into the LLM prompt.
"""

from __future__ import annotations

from .mcus import MCUS
from .power import POWER
from .passives import PASSIVES
from .connectors import CONNECTORS
from .interfaces import INTERFACES
from .memory import MEMORY
from .sensors import SENSORS
from .motor_relay import MOTOR_RELAY

# Unified catalog: list of all parts
ALL_PARTS = MCUS + POWER + PASSIVES + CONNECTORS + INTERFACES + MEMORY + SENSORS + MOTOR_RELAY

# Index by category for fast lookup
_BY_CATEGORY: dict[str, list[dict]] = {}
for _part in ALL_PARTS:
    cat = _part.get("category", "other")
    _BY_CATEGORY.setdefault(cat, []).append(_part)


def search(query: str, max_results: int = 20) -> list[dict]:
    """Search catalog by keyword (MPN, description, category, package)."""
    q = query.lower()
    results = []
    for part in ALL_PARTS:
        score = 0
        if q in part["mpn"].lower():
            score += 10
        if q in part["description"].lower():
            score += 5
        if q in part.get("category", "").lower():
            score += 3
        if q in part.get("package", "").lower():
            score += 2
        # Check key_specs values
        for v in part.get("key_specs", {}).values():
            if isinstance(v, str) and q in v.lower():
                score += 2
        if score > 0:
            results.append((score, part))

    results.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in results[:max_results]]


def find_by_category(category: str) -> list[dict]:
    """Find all parts in a category (exact match)."""
    return _BY_CATEGORY.get(category, [])


def find_mcu(keywords: str = "") -> list[dict]:
    """Find MCUs matching keywords like 'arm', 'cortex', 'esp32', etc."""
    if not keywords:
        return MCUS
    return search(keywords, max_results=10)


def find_for_request(request: str) -> str:
    """Given a user's board request, return a curated component list.

    Analyzes the request and returns relevant parts from each category
    that the LLM should use.  Formatted as text for prompt injection.
    """
    low = request.lower()
    lines = ["## Recommended Components from Catalog\n"]
    lines.append("Use these REAL parts in your design (mpn → package):\n")

    # ── MCU selection ──────────────────────────────────────────────────
    mcus = []
    if "stm32mp" in low or "cortex-a" in low or "cortex a" in low:
        mcus = [p for p in MCUS if p["category"] == "arm_cortex_a"]
    elif "stm32" in low:
        mcus = [p for p in MCUS if "STM32" in p["mpn"]
                and p["category"] == "arm_cortex_m"]
    elif "nrf" in low or "ble" in low or "bluetooth" in low:
        mcus = [p for p in MCUS if "NRF" in p["mpn"]]
    elif "rp2040" in low or "raspberry" in low:
        mcus = [p for p in MCUS if "RP2040" in p["mpn"]]
    elif "esp32" in low:
        mcus = [p for p in MCUS if p["category"] == "esp32"]
    elif "avr" in low or "atmega" in low or "attiny" in low:
        mcus = [p for p in MCUS if p["category"] == "avr"]
    elif "arm" in low or "cortex" in low:
        mcus = [p for p in MCUS
                if p["category"] in ("arm_cortex_m", "arm_cortex_a")]
    else:
        mcus = MCUS[:5]  # Default selection

    if mcus:
        lines.append("### MCU / Processor")
        for p in mcus[:5]:
            specs = p.get("key_specs", {})
            lines.append(f"  {p['mpn']} ({p['package']}): {p['description']}")
            if "core" in specs:
                lines.append(f"    Core: {specs['core']}, {specs.get('freq_mhz', '?')}MHz")
        lines.append("")

    # ── Memory ─────────────────────────────────────────────────────────
    if any(k in low for k in ["ddr", "ram", "sdram", "memory", "arm", "cortex-a",
                               "coreboard", "core board", "sbc"]):
        lines.append("### Memory")
        for p in find_by_category("ddr3")[:3]:
            lines.append(f"  {p['mpn']} ({p['package']}): {p['description']}")
        for p in find_by_category("spi_flash")[:2]:
            lines.append(f"  {p['mpn']} ({p['package']}): {p['description']}")
        for p in find_by_category("eeprom")[:1]:
            lines.append(f"  {p['mpn']} ({p['package']}): {p['description']}")
        lines.append("")

    # ── Power ──────────────────────────────────────────────────────────
    lines.append("### Power Supply")
    power_cats = []
    if any(k in low for k in ["buck", "high current", "6a", "motor",
                               "arm", "cortex", "ddr"]):
        power_cats.append("buck")
    power_cats.append("ldo")
    if any(k in low for k in ["reset", "supervisor", "arm", "cortex"]):
        power_cats.append("supervisor")
    if any(k in low for k in ["protection", "esd", "tvs", "reverse"]):
        power_cats.extend(["esd", "tvs", "schottky"])

    for cat in power_cats:
        for p in find_by_category(cat)[:3]:
            lines.append(f"  {p['mpn']} ({p['package']}): {p['description']}")
    lines.append("")

    # ── Interfaces ─────────────────────────────────────────────────────
    if any(k in low for k in ["usb", "uart", "serial", "ch340", "cp2102"]):
        lines.append("### USB/UART Interface")
        for p in find_by_category("usb_uart")[:3]:
            lines.append(f"  {p['mpn']} ({p['package']}): {p['description']}")
        lines.append("")

    if any(k in low for k in ["pd", "power delivery", "usb pd", "usb-pd"]):
        lines.append("### USB PD Controllers")
        for p in find_by_category("usb_pd"):
            lines.append(f"  {p['mpn']} ({p['package']}): {p['description']}")
        lines.append("")

    if any(k in low for k in ["ethernet", "lan", "rj45", "network"]):
        lines.append("### Ethernet")
        for p in find_by_category("ethernet_phy")[:3]:
            lines.append(f"  {p['mpn']} ({p['package']}): {p['description']}")
        lines.append("")

    if any(k in low for k in ["can", "canbus", "can bus"]):
        lines.append("### CAN Bus")
        for p in find_by_category("can"):
            lines.append(f"  {p['mpn']} ({p['package']}): {p['description']}")
        lines.append("")

    if any(k in low for k in ["rs485", "rs-485", "modbus"]):
        lines.append("### RS-485")
        for p in find_by_category("rs485"):
            lines.append(f"  {p['mpn']} ({p['package']}): {p['description']}")
        lines.append("")

    # ── Sensors ────────────────────────────────────────────────────────
    if any(k in low for k in ["sensor", "temperature", "humidity", "pressure",
                               "accel", "gyro", "imu", "current", "adc",
                               "thermocouple", "load cell", "light"]):
        lines.append("### Sensors")
        sensor_cats = set()
        if "temp" in low or "humidity" in low or "pressure" in low or "weather" in low:
            sensor_cats.add("environmental")
        if "accel" in low or "gyro" in low or "imu" in low or "motion" in low:
            sensor_cats.update(["imu", "accelerometer"])
        if "current" in low or "power monitor" in low:
            sensor_cats.add("current_sensor")
        if "adc" in low or "analog" in low:
            sensor_cats.add("adc")
        if "thermo" in low:
            sensor_cats.add("thermocouple")
        if "light" in low or "lux" in low:
            sensor_cats.add("light")
        if not sensor_cats:
            sensor_cats = {"environmental", "imu", "current_sensor"}

        for cat in sensor_cats:
            for p in find_by_category(cat)[:2]:
                lines.append(f"  {p['mpn']} ({p['package']}): {p['description']}")
        lines.append("")

    # ── Motor/Relay ────────────────────────────────────────────────────
    if any(k in low for k in ["motor", "stepper", "h-bridge", "h bridge",
                               "servo", "actuator"]):
        lines.append("### Motor Drivers")
        for p in (find_by_category("motor_driver")[:2]
                  + find_by_category("stepper_driver")[:2]):
            lines.append(f"  {p['mpn']} ({p['package']}): {p['description']}")
        lines.append("")

    if "relay" in low:
        lines.append("### Relays")
        for p in find_by_category("relay")[:2]:
            lines.append(f"  {p['mpn']} ({p['package']}): {p['description']}")
        for p in find_by_category("darlington_array")[:1]:
            lines.append(f"  {p['mpn']} ({p['package']}): {p['description']}")
        lines.append("")

    # ── Connectors ─────────────────────────────────────────────────────
    lines.append("### Connectors")
    if "usb-c" in low or "usb c" in low or "type-c" in low or "type c" in low:
        for p in find_by_category("usb_c"):
            lines.append(f"  {p['mpn']} ({p['package']}): {p['description']}")
    if "micro usb" in low or "usb micro" in low:
        for p in find_by_category("usb_micro"):
            lines.append(f"  {p['mpn']} ({p['package']}): {p['description']}")
    if "barrel" in low or "dc jack" in low:
        for p in find_by_category("barrel_jack"):
            lines.append(f"  {p['mpn']} ({p['package']}): {p['description']}")
    if "sd" in low or "microsd" in low:
        for p in find_by_category("card_slot"):
            lines.append(f"  {p['mpn']} ({p['package']}): {p['description']}")
    for p in find_by_category("header")[:2]:
        lines.append(f"  {p['mpn']} ({p['package']}): {p['description']}")
    lines.append("")

    # ── Passives reminder ──────────────────────────────────────────────
    lines.append("### Essential Passives (always include)")
    lines.append("  100nF 0402/0603 X7R — decoupling (1 per VDD pin)")
    lines.append("  4.7uF 0603 X5R — bulk decoupling")
    lines.append("  10uF 0805 X5R — regulator I/O caps")
    lines.append("  10K 0603 — pull-up/pull-down")
    lines.append("  4.7K 0603 — I2C pull-up")
    lines.append("  330R 0603 — LED current limit (10mA @ 3.3V)")
    lines.append("  Crystals: 8MHz (STM32), 24MHz (USB), 32.768kHz (RTC)")
    lines.append("")

    return "\n".join(lines)


def catalog_summary() -> str:
    """Return a compact summary of the entire catalog for the system prompt."""
    lines = [f"Component catalog: {len(ALL_PARTS)} real parts available"]
    lines.append("Categories: " + ", ".join(sorted(_BY_CATEGORY.keys())))
    lines.append(f"MCUs: {len(MCUS)} | Power: {len(POWER)} | "
                 f"Passives: {len(PASSIVES)} | Connectors: {len(CONNECTORS)} | "
                 f"Interfaces: {len(INTERFACES)} | Memory: {len(MEMORY)} | "
                 f"Sensors: {len(SENSORS)} | Motor/Relay: {len(MOTOR_RELAY)}")
    return "\n".join(lines)
