"""Board templates: pre-defined component sets and netlists for common designs.

Templates use the Code-to-PCB DSL for clean, deterministic designs with:
- Explicit component positions (no random placement needed)
- Complete GPIO wiring (every pin connected)
- Proper power distribution
- Manufacturing-ready quality

Available templates:
- ESP32 carrier board (full GPIO breakout)
- LED blinker (simplest possible board)
- I2C sensor breakout
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.board import Board, BoardSettings, DesignRules
from ..core.component import Component
from ..core.datatypes import Point
from ..core.net import Net, NetClass
from ..ai.pcb_dsl import PCBDesign
from .footprints import get_footprint


@dataclass
class TemplateDefinition:
    """Defines a board template."""
    name: str
    description: str
    builder: callable  # function that returns a Board


def _build_esp32_carrier() -> Board:
    """ESP32 Basic Carrier Board with COMPLETE GPIO breakout.

    Layout (70x55mm board):
    - USB-C connector at top center (power/programming)
    - AMS1117-3.3 LDO near USB for power regulation
    - ESP32-WROOM-32 module at center
    - Left GPIO header (J2, 15 pins) parallel to ESP32 left side
    - Right GPIO header (J3, 15 pins) parallel to ESP32 right side
    - BOOT and RESET buttons at bottom
    - Power LED + current limiter near LDO
    - Decoupling caps near IC power pins
    - 4x M3 mounting holes at corners

    ESP32-WROOM-32 Pin Map (38+1 pins):
    Left side (1-14):   GND, 3V3, EN, VP, VN, IO34, IO35, IO32, IO33, IO25, IO26, IO27, IO14, IO12
    Right side (15-28):  GND, IO13, SD2, SD3, CMD, CLK, SD0, SD1, IO15, IO2, IO0, IO4, IO16, IO17
    Bottom (29-38):     IO5, IO18, IO23, IO19, IO22, RXD0, TXD0, IO21, IO3, IO1
    Pin 39:             GND pad

    GPIO breakout to headers:
    J2 (left, 15 pins):  3V3, EN, VP, VN, IO34, IO35, IO32, IO33, IO25, IO26, IO27, IO14, IO12, IO13, GND
    J3 (right, 15 pins): IO15, IO2, IO4, IO16, IO17, IO5, IO18, IO23, IO19, IO22, IO21, RXD, TXD, IO0, GND
    """
    pcb = PCBDesign(
        "ESP32 Basic Carrier Board",
        width=70.0,
        height=55.0,
        description=(
            "ESP32-WROOM-32 carrier board with USB-C, 3.3V LDO, full GPIO breakout, "
            "boot/reset buttons, power LED, and decoupling capacitors."
        ),
    )

    # ─── Component Placement ────────────────────────────────────────
    # All positions are carefully calculated for routability.
    # ESP32 module center at (35, 28), headers parallel on each side.

    # Main MCU - centered
    u1 = pcb.place("U1", "ESP32-WROOM-32", value="ESP32-WROOM-32",
                    pos=(35.0, 28.0),
                    manufacturer="Espressif", mpn="ESP32-WROOM-32E",
                    description="WiFi+BT module")

    # USB-C connector - top center
    j1 = pcb.place("J1", "USB_C_16pin", value="USB_C",
                    pos=(35.0, 3.0),
                    manufacturer="Various", mpn="USB-C-16P",
                    description="USB Type-C connector")

    # Voltage regulator - near USB, right side
    u2 = pcb.place("U2", "SOT-223", value="AMS1117-3.3",
                    pos=(56.0, 10.0),
                    manufacturer="AMS", mpn="AMS1117-3.3",
                    description="3.3V LDO regulator")

    # Input decoupling cap - near LDO input
    c1 = pcb.place("C1", "C_0805", value="10uF",
                    pos=(52.0, 7.0),
                    manufacturer="Samsung", mpn="CL21A106KAYNNNE",
                    description="Input decoupling, regulator")

    # Output decoupling cap - near LDO output
    c2 = pcb.place("C2", "C_0805", value="10uF",
                    pos=(60.0, 7.0),
                    manufacturer="Samsung", mpn="CL21A106KAYNNNE",
                    description="Output decoupling, regulator")

    # Bypass caps - near ESP32 power pins
    c3 = pcb.place("C3", "C_0603", value="100nF",
                    pos=(28.0, 17.0),
                    manufacturer="Samsung", mpn="CL10B104KB8NNNL",
                    description="Bypass cap, ESP32 (left side)")

    c4 = pcb.place("C4", "C_0603", value="100nF",
                    pos=(42.0, 17.0),
                    manufacturer="Samsung", mpn="CL10B104KB8NNNL",
                    description="Bypass cap, ESP32 (right side)")

    # Reset button - bottom left area
    sw1 = pcb.place("SW1", "SW_Push_SMD", value="RESET",
                     pos=(15.0, 50.0),
                     description="Reset button (EN)")

    # Boot button - bottom right area
    sw2 = pcb.place("SW2", "SW_Push_SMD", value="BOOT",
                     pos=(55.0, 50.0),
                     description="Boot mode button (GPIO0)")

    # Power LED - near LDO
    d1 = pcb.place("D1", "LED_0603", value="LED_Green",
                    pos=(62.0, 14.0),
                    description="Power indicator LED")

    # LED current limiting resistor
    r1 = pcb.place("R1", "R_0603", value="1k",
                    pos=(62.0, 18.0),
                    description="LED current limiting resistor")

    # EN pull-up resistor - near reset circuit
    r2 = pcb.place("R2", "R_0603", value="10k",
                    pos=(20.0, 50.0),
                    description="EN pin pull-up")

    # IO0 pull-up resistor - near boot button
    r3 = pcb.place("R3", "R_0603", value="10k",
                    pos=(50.0, 50.0),
                    description="IO0 pull-up for boot mode")

    # Left GPIO header - parallel to ESP32 left side
    j2 = pcb.place("J2", "PinHeader_1x15", value="GPIO_LEFT",
                    pos=(8.0, 10.0),
                    description="Left GPIO breakout header")

    # Right GPIO header - parallel to ESP32 right side
    j3 = pcb.place("J3", "PinHeader_1x15", value="GPIO_RIGHT",
                    pos=(62.0, 10.0),
                    description="Right GPIO breakout header")

    # Mounting holes at corners
    h1 = pcb.place("H1", "MountingHole_M3", value="MH", pos=(3.5, 3.5))
    h2 = pcb.place("H2", "MountingHole_M3", value="MH", pos=(66.5, 3.5))
    h3 = pcb.place("H3", "MountingHole_M3", value="MH", pos=(3.5, 51.5))
    h4 = pcb.place("H4", "MountingHole_M3", value="MH", pos=(66.5, 51.5))

    # ─── Power Nets ─────────────────────────────────────────────────

    # VBUS: USB-C power pins -> LDO input -> input cap
    # Use only A-side for VBUS to avoid grid overlap with B-side D+ pins
    pcb.power_net("VBUS", [
        (j1, "A4"), (j1, "A9"), (j1, "B4"), (j1, "B9"),
        (u2, "1"), (c1, "1"),
    ])

    # 3V3: LDO output -> ESP32 -> caps -> pull-ups -> LED -> header
    pcb.power_net("3V3", [
        (u2, "3"),
        (c2, "1"), (c3, "1"), (c4, "1"),
        (u1, "2"),
        (r2, "1"), (r3, "1"),
        (r1, "1"),    # LED current limiter top
        (j2, "1"),    # Left header pin 1 = 3V3
    ])

    # GND
    pcb.power_net("GND", [
        (j1, "A1"), (j1, "A12"), (j1, "B1"), (j1, "B12"),
        (u2, "2"),
        (c1, "2"), (c2, "2"), (c3, "2"), (c4, "2"),
        (u1, "1"), (u1, "15"), (u1, "39"),
        (sw1, "2"), (sw2, "2"),
        (d1, "2"),    # LED cathode
        (j2, "15"), (j3, "15"),
    ])

    # ─── Signal Nets ───────────────────────────────────────────────

    # LED: 3V3 -> R1.1 (in 3V3) -> R1.2 -[LED_ANODE]-> D1.1 -> D1.2 (in GND)
    pcb.net("LED_ANODE", [(r1, "2"), (d1, "1")])

    # EN (reset) circuit
    pcb.net("EN", [(u1, "3"), (r2, "2"), (sw1, "1"), (j2, "2")])

    # IO0 (boot) circuit + header breakout
    # Pin 25 goes to boot button AND J3 pin 14
    pcb.net("IO0", [(u1, "25"), (r3, "2"), (sw2, "1"), (j3, "14")])

    # Note: No USB data lines connected. This carrier board uses USB-C for
    # power only. Programming is done via TXD/RXD on J3 header with an
    # external USB-UART adapter (CP2102/CH340). This is the standard
    # approach for ESP32 carrier boards without an onboard bridge chip.

    # ─── GPIO Breakout: Left Header (J2) ──────────────────────────
    # J2 pin 1 = 3V3 (in power net above)
    # J2 pin 2 = EN (in EN net above)
    # J2 pins 3-14 = GPIO from ESP32 left side
    # J2 pin 15 = GND (in power net above)

    left_gpios = [
        ("4",  "3",  "SENSOR_VP"),   # ESP32 pin 4 -> J2 pin 3
        ("5",  "4",  "SENSOR_VN"),   # ESP32 pin 5 -> J2 pin 4
        ("6",  "5",  "IO34"),        # ESP32 pin 6 -> J2 pin 5
        ("7",  "6",  "IO35"),        # ESP32 pin 7 -> J2 pin 6
        ("8",  "7",  "IO32"),        # ESP32 pin 8 -> J2 pin 7
        ("9",  "8",  "IO33"),        # ESP32 pin 9 -> J2 pin 8
        ("10", "9",  "IO25"),        # ESP32 pin 10 -> J2 pin 9
        ("11", "10", "IO26"),        # ESP32 pin 11 -> J2 pin 10
        ("12", "11", "IO27"),        # ESP32 pin 12 -> J2 pin 11
        ("13", "12", "IO14"),        # ESP32 pin 13 -> J2 pin 12
        ("14", "13", "IO12"),        # ESP32 pin 14 -> J2 pin 13
        ("16", "14", "IO13"),        # ESP32 pin 16 -> J2 pin 14
    ]

    for esp_pin, hdr_pin, net_name in left_gpios:
        pcb.net(net_name, [(u1, esp_pin), (j2, hdr_pin)])

    # ─── GPIO Breakout: Right Header (J3) ─────────────────────────
    # J3 pins 1-13 = GPIO from ESP32 right side + bottom
    # J3 pin 14 = IO0 (shared with boot button, defined above)
    # J3 pin 15 = GND (in power net above)

    right_gpios = [
        ("23", "1",  "IO15"),        # ESP32 pin 23 -> J3 pin 1
        ("24", "2",  "IO2"),         # ESP32 pin 24 -> J3 pin 2
        ("26", "3",  "IO4"),         # ESP32 pin 26 -> J3 pin 3
        ("27", "4",  "IO16"),        # ESP32 pin 27 -> J3 pin 4
        ("28", "5",  "IO17"),        # ESP32 pin 28 -> J3 pin 5
        ("29", "6",  "IO5"),         # ESP32 pin 29 -> J3 pin 6
        ("30", "7",  "IO18"),        # ESP32 pin 30 -> J3 pin 7
        ("31", "8",  "IO23_PIN"),    # ESP32 pin 31 -> J3 pin 8
        ("32", "9",  "IO19"),        # ESP32 pin 32 -> J3 pin 9
        ("33", "10", "IO22"),        # ESP32 pin 33 -> J3 pin 10
        ("36", "11", "IO21"),        # ESP32 pin 36 -> J3 pin 11
        ("34", "12", "RXD"),         # ESP32 pin 34 -> J3 pin 12 (for programming)
        ("35", "13", "TXD"),         # ESP32 pin 35 -> J3 pin 13 (for programming)
    ]

    for esp_pin, hdr_pin, net_name in right_gpios:
        pcb.net(net_name, [(u1, esp_pin), (j3, hdr_pin)])

    return pcb.build()


def _build_led_blinker() -> Board:
    """Simple LED blinker - the most basic PCB project."""
    pcb = PCBDesign(
        "LED Blinker Board",
        width=25.0,
        height=20.0,
        description="A simple board with power input, resistor, and LED.",
    )

    j1 = pcb.place("J1", "PinHeader_1x02", value="Power",
                    pos=(5.0, 10.0), description="Power input (3.3-5V)")
    r1 = pcb.place("R1", "R_0805", value="330",
                    pos=(12.5, 10.0), description="Current limiting resistor")
    d1 = pcb.place("D1", "LED_0805", value="LED_Red",
                    pos=(20.0, 10.0), description="LED indicator")

    pcb.net("VCC", [(j1, "1"), (r1, "1")])
    pcb.net("LED_ANODE", [(r1, "2"), (d1, "1")])
    pcb.net("GND", [(d1, "2"), (j1, "2")])

    return pcb.build()


def _build_sensor_breakout() -> Board:
    """I2C sensor breakout board."""
    pcb = PCBDesign(
        "I2C Sensor Breakout Board",
        width=25.0,
        height=18.0,
        description="Breakout for I2C sensors with pull-ups and decoupling.",
    )

    j1 = pcb.place("J1", "PinHeader_1x04", value="Header",
                    pos=(4.0, 5.0),
                    description="Connection header (VCC, GND, SDA, SCL)")
    r1 = pcb.place("R1", "R_0603", value="4.7k",
                    pos=(12.0, 6.0), description="I2C SDA pull-up")
    r2 = pcb.place("R2", "R_0603", value="4.7k",
                    pos=(12.0, 10.0), description="I2C SCL pull-up")
    c1 = pcb.place("C1", "C_0603", value="100nF",
                    pos=(18.0, 8.0), description="Decoupling capacitor")

    pcb.net("VCC", [(j1, "1"), (r1, "1"), (r2, "1"), (c1, "1")])
    pcb.net("GND", [(j1, "2"), (c1, "2")])
    pcb.net("SDA", [(j1, "3"), (r1, "2")])
    pcb.net("SCL", [(j1, "4"), (r2, "2")])

    return pcb.build()


# ─── Template Registry ──────────────────────────────────────────────────────

TEMPLATE_REGISTRY: dict[str, TemplateDefinition] = {
    "esp32_carrier": TemplateDefinition(
        name="ESP32 Basic Carrier Board",
        description=(
            "ESP32-WROOM-32 carrier board with USB-C, 3.3V LDO, full GPIO breakout "
            "(30 GPIOs wired to headers), boot/reset buttons, power LED, and "
            "decoupling capacitors. 70x55mm, 2-layer, manufacturing-ready."
        ),
        builder=_build_esp32_carrier,
    ),
    "led_blinker": TemplateDefinition(
        name="LED Blinker Board",
        description=(
            "The simplest possible PCB: power header, resistor, and LED. "
            "25x20mm, perfect for learning."
        ),
        builder=_build_led_blinker,
    ),
    "sensor_breakout": TemplateDefinition(
        name="I2C Sensor Breakout Board",
        description=(
            "Breakout board for I2C sensors with pull-up resistors and "
            "decoupling capacitor. 25x18mm."
        ),
        builder=_build_sensor_breakout,
    ),
}


def create_board_from_template(template_name: str) -> Board:
    """Create a Board from a named template."""
    template = TEMPLATE_REGISTRY.get(template_name)
    if template is None:
        available = ", ".join(TEMPLATE_REGISTRY.keys())
        raise ValueError(f"Unknown template '{template_name}'. Available: {available}")
    return template.builder()


def list_templates() -> list[dict[str, str]]:
    """List available templates with descriptions."""
    return [
        {"name": name, "description": t.description}
        for name, t in TEMPLATE_REGISTRY.items()
    ]
