"""Board templates: pre-defined component sets and netlists for common designs.

Phase 1 focuses on simple boards:
- ESP32 carrier/breakout boards
- LED blinker circuits
- Power supply boards
- Sensor breakout boards
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.board import Board, BoardSettings, DesignRules
from ..core.component import Component
from ..core.datatypes import Point
from ..core.net import Net, NetClass
from .footprints import get_footprint


@dataclass
class TemplateDefinition:
    """Defines a board template that the AI can use to create a design."""
    name: str
    description: str
    board_width: float  # mm
    board_height: float  # mm
    components: list[dict] = field(default_factory=list)
    nets: list[dict] = field(default_factory=list)
    net_classes: list[dict] = field(default_factory=list)


def _create_board_from_template(template: TemplateDefinition) -> Board:
    """Convert a template definition into a Board object."""
    board = Board(
        name=template.name,
        description=template.description,
        settings=BoardSettings(
            width=template.board_width,
            height=template.board_height,
        ),
    )

    # Create net classes
    nc_map: dict[str, NetClass] = {}
    for nc_def in template.net_classes:
        nc = NetClass(**nc_def)
        board.net_classes.append(nc)
        nc_map[nc.name] = nc

    # Create nets
    net_map: dict[str, Net] = {}
    for net_def in template.nets:
        nc = nc_map.get(net_def.get("net_class", ""), None)
        net = board.add_net(net_def["name"], nc)
        net_map[net_def["name"]] = net
        for pad_ref in net_def.get("pads", []):
            comp_ref, pad_num = pad_ref.split(".")
            net.add_pad(comp_ref, pad_num)

    # Create components
    for comp_def in template.components:
        fp = get_footprint(comp_def["footprint"])
        if fp is None:
            raise ValueError(f"Unknown footprint: {comp_def['footprint']}")

        comp = Component(
            reference=comp_def["reference"],
            value=comp_def.get("value", ""),
            footprint=fp,
            manufacturer=comp_def.get("manufacturer", ""),
            mpn=comp_def.get("mpn", ""),
            description=comp_def.get("description", ""),
        )
        board.add_component(comp)

        # Assign net IDs to pads
        for pad in comp.footprint.pads:
            for net in board.nets:
                for cref, pnum in net.pad_refs:
                    if cref == comp.reference and pnum == pad.number:
                        pad.net_id = net.id
                        pad.net_name = net.name

    return board


# ─── ESP32 Basic Carrier Board ──────────────────────────────────────────────

ESP32_CARRIER_BASIC = TemplateDefinition(
    name="ESP32 Basic Carrier Board",
    description=(
        "A minimal ESP32-WROOM-32 carrier board with USB-C for power/programming, "
        "3.3V regulator, boot/reset buttons, power LED, GPIO breakout headers, "
        "and decoupling capacitors. Suitable for prototyping and development."
    ),
    board_width=55.0,
    board_height=40.0,
    net_classes=[
        {"name": "Default", "trace_width": 0.25, "clearance": 0.2},
        {"name": "Power", "trace_width": 0.5, "clearance": 0.2},
    ],
    components=[
        # Main MCU
        {
            "reference": "U1",
            "value": "ESP32-WROOM-32",
            "footprint": "ESP32-WROOM-32",
            "manufacturer": "Espressif",
            "mpn": "ESP32-WROOM-32E",
            "description": "WiFi+BT module",
        },
        # Voltage regulator (5V USB -> 3.3V)
        {
            "reference": "U2",
            "value": "AMS1117-3.3",
            "footprint": "SOT-223",
            "manufacturer": "Advanced Monolithic Systems",
            "mpn": "AMS1117-3.3",
            "description": "3.3V LDO regulator",
        },
        # USB connector
        {
            "reference": "J1",
            "value": "USB_C",
            "footprint": "USB_C_16pin",
            "manufacturer": "Various",
            "mpn": "USB-C-16P",
            "description": "USB Type-C connector for power and data",
        },
        # Decoupling capacitors
        {
            "reference": "C1",
            "value": "10uF",
            "footprint": "C_0805",
            "manufacturer": "Samsung",
            "mpn": "CL21A106KAYNNNE",
            "description": "Input decoupling, regulator",
        },
        {
            "reference": "C2",
            "value": "10uF",
            "footprint": "C_0805",
            "manufacturer": "Samsung",
            "mpn": "CL21A106KAYNNNE",
            "description": "Output decoupling, regulator",
        },
        {
            "reference": "C3",
            "value": "100nF",
            "footprint": "C_0603",
            "manufacturer": "Samsung",
            "mpn": "CL10B104KB8NNNL",
            "description": "Bypass cap, ESP32",
        },
        {
            "reference": "C4",
            "value": "100nF",
            "footprint": "C_0603",
            "manufacturer": "Samsung",
            "mpn": "CL10B104KB8NNNL",
            "description": "Bypass cap, ESP32",
        },
        # Boot and reset buttons
        {
            "reference": "SW1",
            "value": "RESET",
            "footprint": "SW_Push_SMD",
            "description": "Reset button",
        },
        {
            "reference": "SW2",
            "value": "BOOT",
            "footprint": "SW_Push_SMD",
            "description": "Boot mode button (GPIO0)",
        },
        # Power LED with current limiting resistor
        {
            "reference": "D1",
            "value": "LED_Green",
            "footprint": "LED_0603",
            "description": "Power indicator LED",
        },
        {
            "reference": "R1",
            "value": "1k",
            "footprint": "R_0603",
            "description": "LED current limiting resistor",
        },
        # EN pull-up resistor
        {
            "reference": "R2",
            "value": "10k",
            "footprint": "R_0603",
            "description": "EN pin pull-up",
        },
        # IO0 pull-up resistor
        {
            "reference": "R3",
            "value": "10k",
            "footprint": "R_0603",
            "description": "IO0 pull-up for boot mode",
        },
        # GPIO breakout headers
        {
            "reference": "J2",
            "value": "GPIO_LEFT",
            "footprint": "PinHeader_1x15",
            "description": "Left GPIO breakout header",
        },
        {
            "reference": "J3",
            "value": "GPIO_RIGHT",
            "footprint": "PinHeader_1x15",
            "description": "Right GPIO breakout header",
        },
        # Mounting holes
        {
            "reference": "H1",
            "value": "MountingHole",
            "footprint": "MountingHole_M3",
            "description": "Mounting hole",
        },
        {
            "reference": "H2",
            "value": "MountingHole",
            "footprint": "MountingHole_M3",
            "description": "Mounting hole",
        },
        {
            "reference": "H3",
            "value": "MountingHole",
            "footprint": "MountingHole_M3",
            "description": "Mounting hole",
        },
        {
            "reference": "H4",
            "value": "MountingHole",
            "footprint": "MountingHole_M3",
            "description": "Mounting hole",
        },
    ],
    nets=[
        # Power nets
        {"name": "VBUS", "net_class": "Power", "pads": ["J1.A4", "J1.A9", "U2.1", "C1.1"]},
        {
            "name": "3V3",
            "net_class": "Power",
            "pads": [
                "U2.3", "U2.2", "C2.1", "C3.1", "C4.1",
                "U1.2", "R2.1", "R3.1", "R1.1",
            ],
        },
        {
            "name": "GND",
            "net_class": "Power",
            "pads": [
                "J1.A1", "J1.A12", "U2.2", "C1.2", "C2.2", "C3.2", "C4.2",
                "U1.1", "U1.15", "U1.39",
                "SW1.2", "SW2.2", "D1.2",
            ],
        },
        # Reset circuit
        {"name": "EN", "pads": ["U1.3", "R2.2", "SW1.1"]},
        # Boot mode
        {"name": "IO0", "pads": ["U1.25", "R3.2", "SW2.1"]},
        # USB data lines
        {"name": "USB_D+", "pads": ["J1.A6", "U1.35"]},
        {"name": "USB_D-", "pads": ["J1.A7", "U1.34"]},
        # LED
        {"name": "LED_ANODE", "pads": ["R1.2", "D1.1"]},
    ],
)


# ─── LED Blinker (Simple 555 Timer) ─────────────────────────────────────────

LED_BLINKER = TemplateDefinition(
    name="LED Blinker Board",
    description=(
        "A simple board with a power input, current limiting resistor, and LED. "
        "The most basic possible PCB project - good for learning."
    ),
    board_width=25.0,
    board_height=20.0,
    net_classes=[
        {"name": "Default", "trace_width": 0.3, "clearance": 0.2},
    ],
    components=[
        {
            "reference": "J1",
            "value": "Power",
            "footprint": "PinHeader_1x02",
            "description": "Power input header (3.3-5V)",
        },
        {
            "reference": "R1",
            "value": "330",
            "footprint": "R_0805",
            "description": "Current limiting resistor",
        },
        {
            "reference": "D1",
            "value": "LED_Red",
            "footprint": "LED_0805",
            "description": "LED indicator",
        },
    ],
    nets=[
        {"name": "VCC", "pads": ["J1.1", "R1.1"]},
        {"name": "LED_ANODE", "pads": ["R1.2", "D1.1"]},
        {"name": "GND", "pads": ["D1.2", "J1.2"]},
    ],
)


# ─── Sensor Breakout Board ──────────────────────────────────────────────────

SENSOR_BREAKOUT = TemplateDefinition(
    name="I2C Sensor Breakout Board",
    description=(
        "A breakout board for I2C sensors with pull-up resistors, "
        "decoupling capacitor, and pin header for easy breadboard use."
    ),
    board_width=20.0,
    board_height=15.0,
    net_classes=[
        {"name": "Default", "trace_width": 0.25, "clearance": 0.2},
    ],
    components=[
        {
            "reference": "J1",
            "value": "Header",
            "footprint": "PinHeader_1x04",
            "description": "Connection header (VCC, GND, SDA, SCL)",
        },
        {
            "reference": "R1",
            "value": "4.7k",
            "footprint": "R_0603",
            "description": "I2C SDA pull-up",
        },
        {
            "reference": "R2",
            "value": "4.7k",
            "footprint": "R_0603",
            "description": "I2C SCL pull-up",
        },
        {
            "reference": "C1",
            "value": "100nF",
            "footprint": "C_0603",
            "description": "Decoupling capacitor",
        },
    ],
    nets=[
        {"name": "VCC", "pads": ["J1.1", "R1.1", "R2.1", "C1.1"]},
        {"name": "GND", "pads": ["J1.2", "C1.2"]},
        {"name": "SDA", "pads": ["J1.3", "R1.2"]},
        {"name": "SCL", "pads": ["J1.4", "R2.2"]},
    ],
)


# ─── Template Registry ──────────────────────────────────────────────────────

TEMPLATE_REGISTRY: dict[str, TemplateDefinition] = {
    "esp32_carrier": ESP32_CARRIER_BASIC,
    "led_blinker": LED_BLINKER,
    "sensor_breakout": SENSOR_BREAKOUT,
}


def create_board_from_template(template_name: str) -> Board:
    """Create a Board from a named template."""
    template = TEMPLATE_REGISTRY.get(template_name)
    if template is None:
        available = ", ".join(TEMPLATE_REGISTRY.keys())
        raise ValueError(f"Unknown template '{template_name}'. Available: {available}")
    return _create_board_from_template(template)


def list_templates() -> list[dict[str, str]]:
    """List available templates with descriptions."""
    return [
        {"name": name, "description": t.description}
        for name, t in TEMPLATE_REGISTRY.items()
    ]
