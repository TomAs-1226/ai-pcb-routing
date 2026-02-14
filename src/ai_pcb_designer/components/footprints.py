"""Standard footprint library with real-world component definitions.

All dimensions are in millimeters and follow IPC-7351 land pattern standards.
These footprints are designed to be manufacturing-ready.
"""

from __future__ import annotations

from ..core.datatypes import DrillType, Layer, PadShape, PadType, Point, Rect
from ..core.component import (
    CourtyardRect,
    Footprint,
    Pad,
    SilkCircle,
    SilkLine,
    SilkRect,
)


def _smd_pad(number: str, x: float, y: float, sx: float, sy: float) -> Pad:
    """Helper to create a top-side SMD pad."""
    return Pad(
        number=number,
        pad_type=PadType.SMD,
        shape=PadShape.RECT if sx != sy else PadShape.CIRCLE,
        position=Point(x, y),
        size_x=sx,
        size_y=sy,
        layers=[Layer.F_CU, Layer.F_MASK, Layer.F_PASTE],
    )


def _tht_pad(number: str, x: float, y: float, pad_size: float, drill: float) -> Pad:
    """Helper to create a through-hole pad."""
    return Pad(
        number=number,
        pad_type=PadType.THT,
        shape=PadShape.CIRCLE,
        position=Point(x, y),
        size_x=pad_size,
        size_y=pad_size,
        drill_size=drill,
        layers=[Layer.F_CU, Layer.B_CU, Layer.F_MASK, Layer.B_MASK],
    )


def _tht_rect_pad(number: str, x: float, y: float, pad_size: float, drill: float) -> Pad:
    """Through-hole pad with rectangular shape (for pin 1)."""
    return Pad(
        number=number,
        pad_type=PadType.THT,
        shape=PadShape.RECT,
        position=Point(x, y),
        size_x=pad_size,
        size_y=pad_size,
        drill_size=drill,
        layers=[Layer.F_CU, Layer.B_CU, Layer.F_MASK, Layer.B_MASK],
    )


def _mounting_hole(x: float, y: float, drill: float = 3.2) -> Pad:
    """Non-plated mounting hole."""
    return Pad(
        number="",
        pad_type=PadType.NPTH,
        shape=PadShape.CIRCLE,
        position=Point(x, y),
        size_x=drill,
        size_y=drill,
        drill_size=drill,
        layers=[Layer.F_CU, Layer.B_CU],
    )


# ─── Resistors ──────────────────────────────────────────────────────────────

def resistor_0402() -> Footprint:
    """0402 (1005 metric) chip resistor."""
    return Footprint(
        name="R_0402_1005Metric",
        description="Resistor SMD 0402 (1005 Metric)",
        pads=[
            _smd_pad("1", -0.48, 0.0, 0.56, 0.62),
            _smd_pad("2", 0.48, 0.0, 0.56, 0.62),
        ],
        silk_lines=[
            SilkLine(Point(-0.15, 0.41), Point(0.15, 0.41)),
            SilkLine(Point(-0.15, -0.41), Point(0.15, -0.41)),
        ],
        courtyard=CourtyardRect(Rect(-0.96, -0.51, 1.92, 1.02)),
    )


def resistor_0603() -> Footprint:
    """0603 (1608 metric) chip resistor."""
    return Footprint(
        name="R_0603_1608Metric",
        description="Resistor SMD 0603 (1608 Metric)",
        pads=[
            _smd_pad("1", -0.75, 0.0, 0.8, 0.95),
            _smd_pad("2", 0.75, 0.0, 0.8, 0.95),
        ],
        silk_lines=[
            SilkLine(Point(-0.24, 0.58), Point(0.24, 0.58)),
            SilkLine(Point(-0.24, -0.58), Point(0.24, -0.58)),
        ],
        courtyard=CourtyardRect(Rect(-1.35, -0.68, 2.70, 1.36)),
    )


def resistor_0805() -> Footprint:
    """0805 (2012 metric) chip resistor."""
    return Footprint(
        name="R_0805_2012Metric",
        description="Resistor SMD 0805 (2012 Metric)",
        pads=[
            _smd_pad("1", -0.9, 0.0, 1.0, 1.45),
            _smd_pad("2", 0.9, 0.0, 1.0, 1.45),
        ],
        silk_lines=[
            SilkLine(Point(-0.26, 0.83), Point(0.26, 0.83)),
            SilkLine(Point(-0.26, -0.83), Point(0.26, -0.83)),
        ],
        courtyard=CourtyardRect(Rect(-1.60, -0.93, 3.20, 1.86)),
    )


# ─── Capacitors ─────────────────────────────────────────────────────────────

def capacitor_0402() -> Footprint:
    fp = resistor_0402()
    fp.name = "C_0402_1005Metric"
    fp.description = "Capacitor SMD 0402 (1005 Metric)"
    return fp


def capacitor_0603() -> Footprint:
    fp = resistor_0603()
    fp.name = "C_0603_1608Metric"
    fp.description = "Capacitor SMD 0603 (1608 Metric)"
    return fp


def capacitor_0805() -> Footprint:
    fp = resistor_0805()
    fp.name = "C_0805_2012Metric"
    fp.description = "Capacitor SMD 0805 (2012 Metric)"
    return fp


# ─── LEDs ───────────────────────────────────────────────────────────────────

def led_0603() -> Footprint:
    """0603 LED footprint."""
    fp = resistor_0603()
    fp.name = "LED_0603_1608Metric"
    fp.description = "LED SMD 0603 (1608 Metric)"
    return fp


def led_0805() -> Footprint:
    """0805 LED footprint."""
    fp = resistor_0805()
    fp.name = "LED_0805_2012Metric"
    fp.description = "LED SMD 0805 (2012 Metric)"
    return fp


# ─── Voltage Regulators ────────────────────────────────────────────────────

def sot23_3() -> Footprint:
    """SOT-23-3 package (common for small voltage regulators, transistors)."""
    return Footprint(
        name="SOT-23-3",
        description="SOT-23-3 package",
        pads=[
            _smd_pad("1", -0.95, 0.65, 0.6, 0.7),   # left bottom
            _smd_pad("2", -0.95, -0.65, 0.6, 0.7),   # left top
            _smd_pad("3", 0.95, 0.0, 0.6, 0.7),      # right
        ],
        silk_lines=[
            SilkLine(Point(-0.55, -1.1), Point(0.55, -1.1)),
            SilkLine(Point(-0.55, 1.1), Point(0.55, 1.1)),
        ],
        courtyard=CourtyardRect(Rect(-1.45, -1.30, 2.90, 2.60)),
    )


def sot223() -> Footprint:
    """SOT-223 package (AMS1117 and similar regulators)."""
    return Footprint(
        name="SOT-223-3_TabPin2",
        description="SOT-223-3, tab is output",
        pads=[
            _smd_pad("1", -2.3, 3.15, 1.2, 2.0),   # input
            _smd_pad("2", 0.0, 3.15, 1.2, 2.0),     # ground
            _smd_pad("3", 2.3, 3.15, 1.2, 2.0),     # output
            _smd_pad("2", 0.0, -3.15, 3.6, 2.0),    # tab (connected to pin 2)
        ],
        silk_lines=[
            SilkLine(Point(-3.5, -2.0), Point(3.5, -2.0)),
            SilkLine(Point(-3.5, 2.0), Point(3.5, 2.0)),
            SilkLine(Point(-3.5, -2.0), Point(-3.5, 2.0)),
            SilkLine(Point(3.5, -2.0), Point(3.5, 2.0)),
        ],
        courtyard=CourtyardRect(Rect(-4.0, -4.35, 8.0, 8.70)),
    )


# ─── USB Connectors ────────────────────────────────────────────────────────

def usb_micro_b() -> Footprint:
    """USB Micro-B receptacle (surface mount, common for ESP32 dev boards)."""
    pads = [
        _smd_pad("1", -1.3, 3.675, 0.4, 1.35),   # VBUS
        _smd_pad("2", -0.65, 3.675, 0.4, 1.35),   # D-
        _smd_pad("3", 0.0, 3.675, 0.4, 1.35),     # D+
        _smd_pad("4", 0.65, 3.675, 0.4, 1.35),    # ID
        _smd_pad("5", 1.3, 3.675, 0.4, 1.35),     # GND
        # Shield pins
        _smd_pad("S1", -3.2, 3.15, 1.6, 2.0),
        _smd_pad("S2", 3.2, 3.15, 1.6, 2.0),
        _smd_pad("S3", -1.0, 0.0, 1.5, 2.0),
        _smd_pad("S4", 1.0, 0.0, 1.5, 2.0),
    ]
    return Footprint(
        name="USB_Micro-B_Molex_47346-0001",
        description="USB Micro-B receptacle",
        pads=pads,
        silk_lines=[
            SilkLine(Point(-4.2, -1.0), Point(4.2, -1.0)),
            SilkLine(Point(-4.2, 4.5), Point(4.2, 4.5)),
        ],
        courtyard=CourtyardRect(Rect(-4.4, -1.5, 8.8, 6.5)),
    )


def usb_c_16pin() -> Footprint:
    """USB Type-C 16-pin receptacle (simplified for power and USB 2.0).

    Two-row layout: A-side pads on the bottom row, B-side on the top row,
    with 0.5mm vertical separation to avoid pad overlaps between different nets.
    """
    pads = [
        # A-side row (y = 6.25) - left to right: A1, A4, A5, A6, A7, A9, A12
        _smd_pad("A1", -3.25, 6.25, 0.3, 0.8),    # GND
        _smd_pad("A4", -2.25, 6.25, 0.3, 0.8),    # VBUS
        _smd_pad("A5", -1.25, 6.25, 0.3, 0.8),    # CC1
        _smd_pad("A6", -0.25, 6.25, 0.3, 0.8),    # D+
        _smd_pad("A7", 0.25, 6.25, 0.3, 0.8),     # D-
        _smd_pad("A9", 1.25, 6.25, 0.3, 0.8),     # VBUS
        _smd_pad("A12", 3.25, 6.25, 0.3, 0.8),    # GND
        # B-side row (y = 5.75) - mirrored: B12, B9, B7, B6, B5, B4, B1
        _smd_pad("B12", -3.25, 5.75, 0.3, 0.8),   # GND
        _smd_pad("B9", -1.25, 5.75, 0.3, 0.8),    # VBUS
        _smd_pad("B7", -0.25, 5.75, 0.3, 0.8),    # D-
        _smd_pad("B6", 0.25, 5.75, 0.3, 0.8),     # D+
        _smd_pad("B5", 1.25, 5.75, 0.3, 0.8),     # CC2
        _smd_pad("B4", 2.25, 5.75, 0.3, 0.8),     # VBUS
        _smd_pad("B1", 3.25, 5.75, 0.3, 0.8),     # GND
        # Shield pins
        _smd_pad("S1", -4.32, 4.515, 1.04, 2.17),
        _smd_pad("S2", 4.32, 4.515, 1.04, 2.17),
    ]
    return Footprint(
        name="USB_C_Receptacle_16pin",
        description="USB Type-C 16-pin receptacle",
        pads=pads,
        silk_lines=[
            SilkLine(Point(-4.97, 0.0), Point(4.97, 0.0)),
            SilkLine(Point(-4.97, 7.0), Point(4.97, 7.0)),
            SilkLine(Point(-4.97, 0.0), Point(-4.97, 7.0)),
            SilkLine(Point(4.97, 0.0), Point(4.97, 7.0)),
        ],
        courtyard=CourtyardRect(Rect(-5.2, -0.3, 10.4, 7.6)),
    )


# ─── Pin Headers ────────────────────────────────────────────────────────────

def pin_header_1x(num_pins: int, pitch: float = 2.54) -> Footprint:
    """Single-row pin header (through-hole)."""
    pads = []
    for i in range(num_pins):
        y = i * pitch
        if i == 0:
            pads.append(_tht_rect_pad(str(i + 1), 0, y, 1.7, 1.0))
        else:
            pads.append(_tht_pad(str(i + 1), 0, y, 1.7, 1.0))

    total_height = (num_pins - 1) * pitch
    return Footprint(
        name=f"PinHeader_1x{num_pins:02d}_P{pitch:.2f}mm_Vertical",
        description=f"1x{num_pins} pin header, {pitch}mm pitch",
        pads=pads,
        silk_lines=[
            SilkLine(Point(-1.33, -1.33), Point(1.33, -1.33)),
            SilkLine(Point(1.33, -1.33), Point(1.33, total_height + 1.33)),
            SilkLine(Point(1.33, total_height + 1.33), Point(-1.33, total_height + 1.33)),
            SilkLine(Point(-1.33, total_height + 1.33), Point(-1.33, -1.33)),
        ],
        courtyard=CourtyardRect(Rect(-1.8, -1.8, 3.6, total_height + 3.6)),
    )


def pin_header_2x(num_pins_per_row: int, pitch: float = 2.54) -> Footprint:
    """Dual-row pin header (through-hole)."""
    pads = []
    for i in range(num_pins_per_row):
        y = i * pitch
        pin_left = i * 2 + 1
        pin_right = i * 2 + 2
        if i == 0:
            pads.append(_tht_rect_pad(str(pin_left), -pitch / 2, y, 1.7, 1.0))
        else:
            pads.append(_tht_pad(str(pin_left), -pitch / 2, y, 1.7, 1.0))
        pads.append(_tht_pad(str(pin_right), pitch / 2, y, 1.7, 1.0))

    total_height = (num_pins_per_row - 1) * pitch
    return Footprint(
        name=f"PinHeader_2x{num_pins_per_row:02d}_P{pitch:.2f}mm_Vertical",
        description=f"2x{num_pins_per_row} pin header, {pitch}mm pitch",
        pads=pads,
        silk_lines=[
            SilkLine(Point(-pitch / 2 - 1.33, -1.33), Point(pitch / 2 + 1.33, -1.33)),
            SilkLine(
                Point(pitch / 2 + 1.33, -1.33),
                Point(pitch / 2 + 1.33, total_height + 1.33),
            ),
            SilkLine(
                Point(pitch / 2 + 1.33, total_height + 1.33),
                Point(-pitch / 2 - 1.33, total_height + 1.33),
            ),
            SilkLine(
                Point(-pitch / 2 - 1.33, total_height + 1.33),
                Point(-pitch / 2 - 1.33, -1.33),
            ),
        ],
        courtyard=CourtyardRect(
            Rect(-pitch / 2 - 1.8, -1.8, pitch + 3.6, total_height + 3.6)
        ),
    )


# ─── ESP32 Module ───────────────────────────────────────────────────────────

def esp32_wroom_32() -> Footprint:
    """ESP32-WROOM-32 module footprint (18x25.5mm, castellated pads).

    This follows the Espressif datasheet dimensions exactly.
    38 pins total: 2 rows of 14 on the long sides + 10 on the bottom.
    Plus the GND pad on the bottom.
    """
    pads = []
    pad_num = 1

    # Bottom row of pads (pins 1-14), left side going down
    # Pin 1 (GND) is at bottom-left
    left_x = -8.0  # left edge pads
    right_x = 8.0  # right edge pads

    # Left side pins (1-14), going from bottom to top
    pin_positions_left = [
        (1, "GND", -8.0, 12.25),
        (2, "3V3", -8.0, 10.98),
        (3, "EN", -8.0, 9.71),
        (4, "SENSOR_VP", -8.0, 8.44),
        (5, "SENSOR_VN", -8.0, 7.17),
        (6, "IO34", -8.0, 5.90),
        (7, "IO35", -8.0, 4.63),
        (8, "IO32", -8.0, 3.36),
        (9, "IO33", -8.0, 2.09),
        (10, "IO25", -8.0, 0.82),
        (11, "IO26", -8.0, -0.45),
        (12, "IO27", -8.0, -1.72),
        (13, "IO14", -8.0, -2.99),
        (14, "IO12", -8.0, -4.26),
    ]

    # Right side pins (15-28), going from bottom to top
    pin_positions_right = [
        (15, "GND", 8.0, -4.26),
        (16, "IO13", 8.0, -2.99),
        (17, "SD2", 8.0, -1.72),
        (18, "SD3", 8.0, -0.45),
        (19, "CMD", 8.0, 0.82),
        (20, "CLK", 8.0, 2.09),
        (21, "SD0", 8.0, 3.36),
        (22, "SD1", 8.0, 4.63),
        (23, "IO15", 8.0, 5.90),
        (24, "IO2", 8.0, 7.17),
        (25, "IO0", 8.0, 8.44),
        (26, "IO4", 8.0, 9.71),
        (27, "IO16", 8.0, 10.98),
        (28, "IO17", 8.0, 12.25),
    ]

    # Bottom pads (29-38)
    pin_positions_bottom = [
        (29, "IO5", -5.715, 13.52),
        (30, "IO18", -4.445, 13.52),
        (31, "IO23", -3.175, 13.52),
        (32, "IO19", -1.905, 13.52),
        (33, "IO22", -0.635, 13.52),
        (34, "RXD0", 0.635, 13.52),
        (35, "TXD0", 1.905, 13.52),
        (36, "IO21", 3.175, 13.52),
        (37, "IO3", 4.445, 13.52),
        (38, "IO1", 5.715, 13.52),
    ]

    for pin_num, _name, x, y in pin_positions_left:
        pads.append(_smd_pad(str(pin_num), x, y, 1.5, 0.9))

    for pin_num, _name, x, y in pin_positions_right:
        pads.append(_smd_pad(str(pin_num), x, y, 1.5, 0.9))

    for pin_num, _name, x, y in pin_positions_bottom:
        pads.append(_smd_pad(str(pin_num), x, y, 0.9, 1.5))

    # Large ground pad on bottom
    pads.append(Pad(
        number="39",
        pad_type=PadType.SMD,
        shape=PadShape.RECT,
        position=Point(0.0, 14.4),
        size_x=6.0,
        size_y=2.4,
        layers=[Layer.F_CU, Layer.F_MASK, Layer.F_PASTE],
    ))

    # Module outline
    silk = [
        SilkLine(Point(-9.0, -12.75), Point(9.0, -12.75)),
        SilkLine(Point(9.0, -12.75), Point(9.0, 12.75)),
        SilkLine(Point(9.0, 12.75), Point(-9.0, 12.75)),
        SilkLine(Point(-9.0, 12.75), Point(-9.0, -12.75)),
    ]

    return Footprint(
        name="ESP32-WROOM-32",
        description="ESP32-WROOM-32 WiFi+BT module (18x25.5mm)",
        pads=pads,
        silk_lines=silk,
        courtyard=CourtyardRect(Rect(-9.5, -13.25, 19.0, 26.5)),
    )


# ─── Crystal / Oscillator ──────────────────────────────────────────────────

def crystal_3215() -> Footprint:
    """3.2x1.5mm crystal (common 32.768kHz)."""
    return Footprint(
        name="Crystal_SMD_3215",
        description="3.2x1.5mm SMD crystal",
        pads=[
            _smd_pad("1", -1.1, 0.0, 1.0, 1.8),
            _smd_pad("2", 1.1, 0.0, 1.0, 1.8),
        ],
        courtyard=CourtyardRect(Rect(-1.85, -1.15, 3.70, 2.30)),
    )


# ─── Buttons ───────────────────────────────────────────────────────────────

def tactile_switch_6mm() -> Footprint:
    """6x6mm tactile push button (through-hole)."""
    return Footprint(
        name="SW_Push_6mm_THT",
        description="6x6mm tactile push button",
        pads=[
            _tht_pad("1", -3.25, -2.25, 2.0, 1.1),
            _tht_pad("1", -3.25, 2.25, 2.0, 1.1),
            _tht_pad("2", 3.25, -2.25, 2.0, 1.1),
            _tht_pad("2", 3.25, 2.25, 2.0, 1.1),
        ],
        silk_lines=[
            SilkLine(Point(-3.0, -3.0), Point(3.0, -3.0)),
            SilkLine(Point(3.0, -3.0), Point(3.0, 3.0)),
            SilkLine(Point(3.0, 3.0), Point(-3.0, 3.0)),
            SilkLine(Point(-3.0, 3.0), Point(-3.0, -3.0)),
        ],
        silk_circles=[SilkCircle(Point(0, 0), 1.75)],
        courtyard=CourtyardRect(Rect(-4.5, -3.5, 9.0, 7.0)),
    )


def tactile_switch_smd() -> Footprint:
    """SMD tactile switch (3x6mm typical)."""
    return Footprint(
        name="SW_Push_SMD_3x6mm",
        description="3x6mm SMD tactile switch",
        pads=[
            _smd_pad("1", -3.1, 0.0, 1.8, 1.1),
            _smd_pad("2", 3.1, 0.0, 1.8, 1.1),
        ],
        silk_lines=[
            SilkLine(Point(-1.5, -3.0), Point(1.5, -3.0)),
            SilkLine(Point(-1.5, 3.0), Point(1.5, 3.0)),
        ],
        courtyard=CourtyardRect(Rect(-4.2, -3.25, 8.4, 6.5)),
    )


# ─── Mounting Holes ─────────────────────────────────────────────────────────

def mounting_hole_m3() -> Footprint:
    """M3 mounting hole (3.2mm drill)."""
    return Footprint(
        name="MountingHole_M3",
        description="M3 mounting hole, 3.2mm drill",
        pads=[_mounting_hole(0, 0, 3.2)],
        courtyard=CourtyardRect(Rect(-3.5, -3.5, 7.0, 7.0)),
    )


def mounting_hole_m2_5() -> Footprint:
    """M2.5 mounting hole."""
    return Footprint(
        name="MountingHole_M2.5",
        description="M2.5 mounting hole, 2.75mm drill",
        pads=[_mounting_hole(0, 0, 2.75)],
        courtyard=CourtyardRect(Rect(-3.0, -3.0, 6.0, 6.0)),
    )


# ─── Addressable RGB LEDs ──────────────────────────────────────────────────

def ws2812b() -> Footprint:
    """WS2812B addressable RGB LED (5050 package, 5x5mm).

    Pin 1 = VDD (power), Pin 2 = DOUT (data out),
    Pin 3 = GND, Pin 4 = DIN (data in).
    """
    return Footprint(
        name="WS2812B",
        description="WS2812B addressable RGB LED, 5050 package",
        pads=[
            _smd_pad("1", -2.45, -1.6, 1.5, 1.0),  # VDD
            _smd_pad("2", -2.45, 1.6, 1.5, 1.0),   # DOUT
            _smd_pad("3", 2.45, 1.6, 1.5, 1.0),    # GND
            _smd_pad("4", 2.45, -1.6, 1.5, 1.0),   # DIN
        ],
        silk_lines=[
            SilkLine(Point(-2.5, -2.5), Point(2.5, -2.5)),
            SilkLine(Point(2.5, -2.5), Point(2.5, 2.5)),
            SilkLine(Point(2.5, 2.5), Point(-2.5, 2.5)),
            SilkLine(Point(-2.5, 2.5), Point(-2.5, -2.5)),
            # Pin 1 marker
            SilkLine(Point(-2.5, -2.5), Point(-1.5, -2.5), 0.2),
        ],
        courtyard=CourtyardRect(Rect(-3.4, -2.75, 6.8, 5.5)),
    )


# ─── Footprint Registry ────────────────────────────────────────────────────

FOOTPRINT_REGISTRY: dict[str, callable] = {
    # Resistors
    "R_0402": resistor_0402,
    "R_0603": resistor_0603,
    "R_0805": resistor_0805,
    # Capacitors
    "C_0402": capacitor_0402,
    "C_0603": capacitor_0603,
    "C_0805": capacitor_0805,
    # LEDs
    "LED_0603": led_0603,
    "LED_0805": led_0805,
    # ICs
    "SOT-23-3": sot23_3,
    "SOT-223": sot223,
    "ESP32-WROOM-32": esp32_wroom_32,
    # Connectors
    "USB_Micro_B": usb_micro_b,
    "USB_C_16pin": usb_c_16pin,
    # Pin headers
    "PinHeader_1x02": lambda: pin_header_1x(2),
    "PinHeader_1x03": lambda: pin_header_1x(3),
    "PinHeader_1x04": lambda: pin_header_1x(4),
    "PinHeader_1x06": lambda: pin_header_1x(6),
    "PinHeader_1x08": lambda: pin_header_1x(8),
    "PinHeader_1x10": lambda: pin_header_1x(10),
    "PinHeader_1x15": lambda: pin_header_1x(15),
    "PinHeader_1x19": lambda: pin_header_1x(19),
    "PinHeader_2x03": lambda: pin_header_2x(3),
    "PinHeader_2x05": lambda: pin_header_2x(5),
    "PinHeader_2x10": lambda: pin_header_2x(10),
    # Oscillators
    "Crystal_3215": crystal_3215,
    # Switches
    "SW_Push_6mm": tactile_switch_6mm,
    "SW_Push_SMD": tactile_switch_smd,
    # Mounting
    "MountingHole_M3": mounting_hole_m3,
    "MountingHole_M2.5": mounting_hole_m2_5,
    # Addressable LEDs
    "WS2812B": ws2812b,
}


def get_footprint(name: str) -> Footprint | None:
    """Look up a footprint by name."""
    factory = FOOTPRINT_REGISTRY.get(name)
    if factory:
        return factory()
    return None


def list_footprints() -> list[str]:
    """List all available footprint names."""
    return sorted(FOOTPRINT_REGISTRY.keys())
