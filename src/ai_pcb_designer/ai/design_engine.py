"""Smart PCB Design Engine -- creates custom boards from natural language.

Instead of matching pre-built templates this engine *composes* a new PCB
design from building blocks (MCU, power supply, LED matrix, headers, etc.)
based on a parsed ``DesignRequest``.  Every section method places real
components via the ``PCBDesign`` DSL and wires the appropriate nets so
that ``pcb.build()`` produces a fully-connected ``Board``.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .pcb_dsl import PCBDesign, PlacedComponent


# ─── Design Request ─────────────────────────────────────────────────────────


@dataclass
class DesignRequest:
    """Parsed description of what the user wants on their PCB."""

    mcu: str = "esp32"
    power: str = "usb-c"
    led_matrix: tuple[int, int] | None = None  # (cols, rows)
    debug_header: bool = False
    gpio_header: bool = False
    gpio_count: int = 10
    i2c: bool = False
    sensors: list[str] = field(default_factory=list)
    leds: int = 0
    logo_text: str = ""
    custom_text: str = ""


# ─── Request Parser ─────────────────────────────────────────────────────────


def parse_request(text: str) -> DesignRequest:
    """Parse a natural-language board description into a ``DesignRequest``.

    The parser uses simple keyword / regex matching -- it is intentionally
    tolerant of variations like "10*10 neopixel", "5x5 ws2812b", etc.
    """
    low = text.lower()
    req = DesignRequest()

    # ── MCU ──────────────────────────────────────────────────────────────
    if "stm32" in low:
        req.mcu = "stm32"
    elif "atmega" in low:
        req.mcu = "atmega"
    elif "esp32" in low:
        req.mcu = "esp32"

    # ── Power ────────────────────────────────────────────────────────────
    if "usb-c" in low or "usb c" in low or "type-c" in low or "type c" in low:
        req.power = "usb-c"
    elif "usb micro" in low or "micro usb" in low or "micro-usb" in low:
        req.power = "usb micro"

    # ── NeoPixel / WS2812B matrix ────────────────────────────────────────
    # Match patterns like "10x10 neopixel", "5*5 ws2812b", "neopixel 8x8",
    # "ws2812 4*4", "led matrix 3x3", etc.
    matrix_pat = re.compile(
        r"(\d+)\s*[x*×]\s*(\d+)\s*(?:neo\s*pixel|ws2812\w*|led|rgb)"
        r"|"
        r"(?:neo\s*pixel|ws2812\w*|led\s*matrix|rgb\s*matrix)\s*(\d+)\s*[x*×]\s*(\d+)",
        re.IGNORECASE,
    )
    m = matrix_pat.search(text)
    if m:
        if m.group(1) and m.group(2):
            cols, rows = int(m.group(1)), int(m.group(2))
        else:
            cols, rows = int(m.group(3)), int(m.group(4))
        req.led_matrix = (cols, rows)
        # Sensible defaults when a NeoPixel matrix is requested
        req.mcu = "esp32"
        req.power = "usb-c"

    # ── Debug header ─────────────────────────────────────────────────────
    if "debug" in low or "serial" in low or "uart" in low:
        req.debug_header = True

    # ── GPIO header ──────────────────────────────────────────────────────
    if "gpio" in low or "header" in low or "breakout" in low:
        req.gpio_header = True
        gpio_count_match = re.search(r"(\d+)\s*(?:gpio|pin)", low)
        if gpio_count_match:
            req.gpio_count = max(2, min(20, int(gpio_count_match.group(1))))

    # ── I2C ──────────────────────────────────────────────────────────────
    if "i2c" in low or "i²c" in low:
        req.i2c = True

    # ── Sensors ──────────────────────────────────────────────────────────
    known_sensors = ["bme280", "bmp280", "mpu6050", "dht22", "dht11", "sht30"]
    for s in known_sensors:
        if s in low:
            req.sensors.append(s)

    # ── Indicator LEDs ───────────────────────────────────────────────────
    led_count_match = re.search(r"(\d+)\s*(?:indicator|status)?\s*led", low)
    if led_count_match:
        # Do not count the matrix size as indicator LEDs
        if req.led_matrix is None or int(led_count_match.group(1)) <= 10:
            req.leds = int(led_count_match.group(1))
    elif "led" in low and req.led_matrix is None:
        req.leds = 1

    # ── Logo / custom text ───────────────────────────────────────────────
    logo_match = re.search(r'logo\s*[:\-]?\s*["\']?([^"\']+?)["\']?\s*(?:$|,)', low)
    if logo_match:
        req.logo_text = logo_match.group(1).strip()
    custom_match = re.search(r'text\s*[:\-]?\s*["\']([^"\']+)["\']', low)
    if custom_match:
        req.custom_text = custom_match.group(1).strip()

    return req


# ─── Design Engine ──────────────────────────────────────────────────────────


class DesignEngine:
    """Composes a new PCB design from building blocks.

    Unlike template-matching the engine creates a fresh ``PCBDesign``
    and adds sections (power, MCU, LED matrix, headers ...) according
    to the ``DesignRequest``.  After composing it runs a validate-and-
    improve loop to push apart overlapping components and grow the
    board if anything falls outside the outline.
    """

    def __init__(self) -> None:
        self._ref_counters: dict[str, int] = {}
        self._log: list[str] = []

    # ── Public API ───────────────────────────────────────────────────────

    @property
    def design_log(self) -> list[str]:
        """Return the list of design decisions taken during the last run."""
        return list(self._log)

    def create_design(self, request: DesignRequest) -> PCBDesign:
        """Create a complete ``PCBDesign`` from a *request*.

        Returns the populated ``PCBDesign`` instance (call ``.build()``
        on it to obtain a ``Board``).
        """
        self._ref_counters.clear()
        self._log.clear()

        # ── Board size ───────────────────────────────────────────────
        if request.led_matrix:
            cols, rows = request.led_matrix
            width = max(70, cols * 10 + 20)
            height = max(55, 50 + rows * 10 + 15)
            self._log.append(
                f"Board sized for {cols}x{rows} LED matrix: "
                f"{width}x{height}mm"
            )
        else:
            width = 70
            height = 55
            self._log.append(f"Default board size: {width}x{height}mm")

        pcb = PCBDesign(
            f"Custom {request.mcu.upper()} Board",
            width=width,
            height=height,
            description="Auto-generated by DesignEngine",
        )
        cx = width / 2  # board centre X

        # ── Power section ────────────────────────────────────────────
        power_comps = self._add_power_section(pcb, request, cx)

        # ── MCU section ──────────────────────────────────────────────
        mcu_comp = self._add_esp32_section(pcb, cx)

        # ── Wire power → MCU ─────────────────────────────────────────
        self._wire_power_to_mcu(pcb, power_comps, mcu_comp)

        # ── Debug header ─────────────────────────────────────────────
        if request.debug_header:
            self._add_debug_header(pcb, mcu_comp, width)

        # ── NeoPixel LED matrix ──────────────────────────────────────
        if request.led_matrix:
            self._add_neopixel_matrix(
                pcb, request.led_matrix, mcu_comp, cx, power_comps,
            )

        # ── GPIO header ──────────────────────────────────────────────
        if request.gpio_header:
            self._add_gpio_header(pcb, mcu_comp, request.gpio_count)

        # ── Indicator LEDs ───────────────────────────────────────────
        if request.leds > 0:
            self._add_indicator_leds(pcb, mcu_comp, request.leds, width)

        # ── Mounting holes ───────────────────────────────────────────
        self._add_mounting_holes(pcb, width, height)

        # ── Logo / text ──────────────────────────────────────────────
        if request.logo_text:
            pcb.text(request.logo_text, pos=(cx, height - 5), font_size=1.5)
            self._log.append(f"Added logo text: '{request.logo_text}'")
        if request.custom_text:
            pcb.text(request.custom_text, pos=(cx, height - 8), font_size=1.0)
            self._log.append(f"Added custom text: '{request.custom_text}'")

        # ── Validate & improve ───────────────────────────────────────
        self._validate_and_improve(pcb)

        return pcb

    # ── Reference Designator Helper ──────────────────────────────────────

    def _next_ref(self, prefix: str) -> str:
        """Return the next reference designator for *prefix* (e.g. ``R``, ``C``)."""
        count = self._ref_counters.get(prefix, 0) + 1
        self._ref_counters[prefix] = count
        return f"{prefix}{count}"

    # ── Power Section ────────────────────────────────────────────────────

    def _add_power_section(
        self,
        pcb: PCBDesign,
        request: DesignRequest,
        cx: float,
    ) -> dict[str, PlacedComponent]:
        """Add USB connector, LDO voltage regulator, and decoupling caps.

        Returns a dict mapping symbolic names to placed components so
        that other sections can reference them for net wiring.
        """
        comps: dict[str, PlacedComponent] = {}

        # USB connector near the top of the board (with margin for bounding rect)
        if request.power == "usb-c":
            usb = pcb.place(
                self._next_ref("J"), "USB_C_16pin", value="USB-C",
                pos=(cx, 8), description="USB Type-C power connector",
            )
        else:
            usb = pcb.place(
                self._next_ref("J"), "USB_Micro_B", value="USB-Micro",
                pos=(cx, 8), description="USB Micro-B power connector",
            )
        comps["usb"] = usb

        # LDO: AMS1117-3.3 in SOT-223 package
        ldo = pcb.place(
            self._next_ref("U"), "SOT-223", value="AMS1117-3.3",
            pos=(cx + 18, 8), description="3.3V LDO regulator",
        )
        comps["ldo"] = ldo

        # Input cap (close to LDO input)
        cin = pcb.place(
            self._next_ref("C"), "C_0805", value="10uF",
            pos=(cx + 14, 12), description="LDO input capacitor",
        )
        comps["cin"] = cin

        # Output cap (close to LDO output)
        cout = pcb.place(
            self._next_ref("C"), "C_0805", value="22uF",
            pos=(cx + 22, 12), description="LDO output capacitor",
        )
        comps["cout"] = cout

        # ── Power nets ───────────────────────────────────────────────
        # VBUS: USB power output → LDO input → input cap
        if request.power == "usb-c":
            pcb.power_net("VBUS", [
                (usb, "A4"), (usb, "A9"),
                (usb, "B9"), (usb, "B4"),
                (ldo, "1"),   # SOT-223 pin 1 = input
                (cin, "1"),
            ])
            pcb.power_net("GND", [
                (usb, "A1"), (usb, "A12"),
                (usb, "B12"), (usb, "B1"),
                (ldo, "2"),   # SOT-223 pin 2 = ground
                (cin, "2"),
                (cout, "2"),
            ])
        else:
            pcb.power_net("VBUS", [
                (usb, "1"),   # Micro-B pin 1 = VBUS
                (ldo, "1"),
                (cin, "1"),
            ])
            pcb.power_net("GND", [
                (usb, "5"),   # Micro-B pin 5 = GND
                (ldo, "2"),
                (cin, "2"),
                (cout, "2"),
            ])

        # 3V3: LDO output → output cap
        pcb.power_net("3V3", [
            (ldo, "3"),   # SOT-223 pin 3 = output
            (cout, "1"),
        ])

        self._log.append(
            f"Power section: {request.power} + AMS1117-3.3 LDO "
            f"with {cin.value} input and {cout.value} output caps"
        )
        return comps

    # ── ESP32 Section ────────────────────────────────────────────────────

    def _add_esp32_section(
        self,
        pcb: PCBDesign,
        cx: float,
    ) -> PlacedComponent:
        """Place the ESP32 module with bypass caps, pull-ups, and buttons.

        Returns the ``PlacedComponent`` for the ESP32 so other sections
        can wire to its pins.
        """
        mcu_y = 28  # vertical centre for the ESP32

        # ESP32 module
        esp = pcb.place(
            self._next_ref("U"), "ESP32-WROOM-32",
            value="ESP32-WROOM-32",
            pos=(cx, mcu_y), description="Main MCU",
        )

        # Bypass / decoupling caps close to the IC (within 3 mm)
        cap1 = pcb.place(
            self._next_ref("C"), "C_0603", value="100nF",
            pos=(cx - 8, mcu_y + 12),
            description="ESP32 bypass cap 1",
        )
        cap2 = pcb.place(
            self._next_ref("C"), "C_0603", value="100nF",
            pos=(cx + 8, mcu_y + 12),
            description="ESP32 bypass cap 2",
        )

        # Pull-up resistors for EN and IO0 (boot mode)
        r_en = pcb.place(
            self._next_ref("R"), "R_0603", value="10k",
            pos=(cx - 14, mcu_y + 10),
            description="EN pull-up resistor",
        )
        r_io0 = pcb.place(
            self._next_ref("R"), "R_0603", value="10k",
            pos=(cx + 14, mcu_y + 10),
            description="IO0 pull-up resistor",
        )

        # Reset and Boot buttons (spaced to avoid overlaps)
        btn_rst = pcb.place(
            self._next_ref("SW"), "SW_Push_6mm", value="RESET",
            pos=(cx - 20, mcu_y + 10),
            description="Reset button",
        )
        btn_boot = pcb.place(
            self._next_ref("SW"), "SW_Push_6mm", value="BOOT",
            pos=(cx + 20, mcu_y + 10),
            description="Boot / IO0 button",
        )

        # ── Net wiring ───────────────────────────────────────────────
        # 3V3 → ESP32 pin 2 + bypass caps pin 1 + pull-up R pin 1
        pcb.power_net("3V3", [
            (esp, "2"),
            (cap1, "1"),
            (cap2, "1"),
            (r_en, "1"),
            (r_io0, "1"),
        ])

        # GND → ESP32 pins 1, 15, 39 + bypass caps pin 2 + button pins
        pcb.power_net("GND", [
            (esp, "1"),
            (esp, "15"),
            (esp, "39"),
            (cap1, "2"),
            (cap2, "2"),
            (btn_rst, "2"),
            (btn_boot, "2"),
        ])

        # EN net: ESP32 pin 3 → pull-up R2 → reset button pin 1
        pcb.net("EN", [
            (esp, "3"),
            (r_en, "2"),
            (btn_rst, "1"),
        ])

        # IO0 net: ESP32 pin 25 → pull-up R → boot button pin 1
        pcb.net("IO0", [
            (esp, "25"),
            (r_io0, "2"),
            (btn_boot, "1"),
        ])

        self._log.append(
            "ESP32 section: module + 2 bypass caps + EN/IO0 pull-ups "
            "+ reset/boot buttons"
        )
        return esp

    # ── Wire Power to MCU ────────────────────────────────────────────────

    def _wire_power_to_mcu(
        self,
        pcb: PCBDesign,
        power_comps: dict[str, PlacedComponent],
        mcu: PlacedComponent,
    ) -> None:
        """Extend the 3V3 and GND nets to include MCU pins.

        The MCU and power section pins are already on these nets via
        their respective ``_add_*`` calls.  This is a no-op if the nets
        are already fully connected, but it ensures the intent is
        recorded in the design log.
        """
        self._log.append(
            "Wired power (3V3 / GND) from LDO to ESP32"
        )

    # ── Debug Header ─────────────────────────────────────────────────────

    def _add_debug_header(
        self,
        pcb: PCBDesign,
        mcu: PlacedComponent,
        board_width: float,
    ) -> PlacedComponent:
        """Add a 1x06 debug / programming header on the right edge.

        Pin-out: 3V3, GND, TXD, RXD, IO0, EN.
        """
        hdr = pcb.place(
            self._next_ref("J"), "PinHeader_1x06", value="DEBUG",
            pos=(board_width - 5, 20),
            description="Debug / programming header",
        )

        # 3V3 on header pin 1
        pcb.power_net("3V3", [(hdr, "1")])
        # GND on header pin 2
        pcb.power_net("GND", [(hdr, "2")])
        # TXD0 (ESP32 pin 35) → header pin 3
        pcb.net("TXD0", [(mcu, "35"), (hdr, "3")])
        # RXD0 (ESP32 pin 34) → header pin 4
        pcb.net("RXD0", [(mcu, "34"), (hdr, "4")])
        # IO0 → header pin 5 (shared with boot button net)
        pcb.net("IO0", [(hdr, "5")])
        # EN → header pin 6 (shared with reset net)
        pcb.net("EN", [(hdr, "6")])

        self._log.append(
            "Debug header (1x06): 3V3, GND, TXD, RXD, IO0, EN on right edge"
        )
        return hdr

    # ── NeoPixel Matrix ──────────────────────────────────────────────────

    def _add_neopixel_matrix(
        self,
        pcb: PCBDesign,
        matrix_size: tuple[int, int],
        mcu: PlacedComponent,
        cx: float,
        power_comps: dict[str, PlacedComponent],
    ) -> list[PlacedComponent]:
        """Place an NxM WS2812B LED matrix with serpentine data wiring.

        * LEDs are placed on a 10 mm pitch grid.
        * Even rows run left-to-right; odd rows run right-to-left
          (serpentine pattern for shorter data traces).
        * Data chain: MCU GPIO5 (pin 29) → first LED DIN, then each
          DOUT → next DIN.
        * LED power is on the ``VBUS`` net (5 V straight from USB).
        * One bulk 100 uF decoupling cap is added per row.

        WS2812B pinout: 1=VDD, 2=DOUT, 3=GND, 4=DIN.
        """
        cols, rows = matrix_size
        pitch = 10.0
        grid_w = (cols - 1) * pitch
        start_x = cx - grid_w / 2
        start_y = 50  # below the MCU area (enough margin for bypass caps)

        leds: list[PlacedComponent] = []
        row_caps: list[PlacedComponent] = []

        # Place LEDs in grid
        for row in range(rows):
            y = start_y + row * pitch

            # Serpentine: even rows L→R, odd rows R→L
            if row % 2 == 0:
                col_range = range(cols)
            else:
                col_range = range(cols - 1, -1, -1)

            for col in col_range:
                x = start_x + col * pitch
                led = pcb.place(
                    self._next_ref("D"), "WS2812B", value="WS2812B",
                    pos=(x, y),
                    description=f"NeoPixel [{row},{col}]",
                )
                leds.append(led)

            # Bulk decoupling cap per row
            cap = pcb.place(
                self._next_ref("C"), "C_0805", value="100uF",
                pos=(start_x + grid_w + 8, y),
                description=f"Row {row} bulk cap",
            )
            row_caps.append(cap)

        # ── Power nets for LEDs ──────────────────────────────────────
        # VDD (pin 1) → VBUS (5 V from USB)
        vbus_pads: list[tuple] = []
        gnd_pads: list[tuple] = []
        for led in leds:
            vbus_pads.append((led, "1"))
            gnd_pads.append((led, "3"))
        for cap in row_caps:
            vbus_pads.append((cap, "1"))
            gnd_pads.append((cap, "2"))

        pcb.power_net("VBUS", vbus_pads)
        pcb.power_net("GND", gnd_pads)

        # ── Data chain (serpentine) ──────────────────────────────────
        # MCU GPIO5 (pin 29) → first LED DIN (pin 4)
        pcb.net("LED_DATA", [(mcu, "29"), (leds[0], "4")])

        # Chain DOUT(pin 2) → next DIN(pin 4)
        for i in range(len(leds) - 1):
            net_name = f"LED_D{i}"
            pcb.net(net_name, [(leds[i], "2"), (leds[i + 1], "4")])

        self._log.append(
            f"NeoPixel matrix: {cols}x{rows} WS2812B LEDs at {pitch}mm "
            f"pitch, serpentine data chain from GPIO5, {len(row_caps)} "
            f"bulk caps"
        )
        return leds

    # ── GPIO Header ──────────────────────────────────────────────────────

    def _add_gpio_header(
        self,
        pcb: PCBDesign,
        mcu: PlacedComponent,
        gpio_count: int,
    ) -> PlacedComponent:
        """Add a 1xN GPIO break-out header on the left edge."""
        # Clamp to available footprint sizes
        size = min(gpio_count, 19)
        # Map to an available pin header footprint name
        available_sizes = [2, 3, 4, 6, 8, 10, 15, 19]
        chosen = min(available_sizes, key=lambda s: abs(s - size))
        fp_name = f"PinHeader_1x{chosen:02d}"

        hdr = pcb.place(
            self._next_ref("J"), fp_name, value=f"GPIO_{chosen}",
            pos=(5, 20),
            description="GPIO break-out header",
        )

        # Map ESP32 GPIO pins to header pins.  These are general-purpose
        # IO pins that are safe to expose:
        # IO32(8), IO33(9), IO25(10), IO26(11), IO27(12),
        # IO14(13), IO12(14), IO13(16), IO4(26), IO16(27)
        esp_gpio_pins = ["8", "9", "10", "11", "12", "13", "14", "16", "26", "27"]
        for i in range(min(chosen, len(esp_gpio_pins))):
            pcb.net(
                f"GPIO_H{i}",
                [(mcu, esp_gpio_pins[i]), (hdr, str(i + 1))],
            )

        self._log.append(
            f"GPIO header (1x{chosen:02d}) on left edge with "
            f"{min(chosen, len(esp_gpio_pins))} GPIOs wired"
        )
        return hdr

    # ── Indicator LEDs ───────────────────────────────────────────────────

    def _add_indicator_leds(
        self,
        pcb: PCBDesign,
        mcu: PlacedComponent,
        count: int,
        board_width: float,
    ) -> list[PlacedComponent]:
        """Add indicator LEDs with current-limiting resistors."""
        placed: list[PlacedComponent] = []
        # Available GPIOs for indicator LEDs (IO2, IO4, IO16, IO17 ...)
        gpio_pins = ["24", "26", "27", "28"]  # IO2, IO4, IO16, IO17

        for i in range(min(count, len(gpio_pins))):
            x = board_width - 10
            y = 40 + i * 6

            led = pcb.place(
                self._next_ref("D"), "LED_0603", value="LED",
                pos=(x, y),
                description=f"Indicator LED {i + 1}",
            )
            res = pcb.place(
                self._next_ref("R"), "R_0603", value="330",
                pos=(x - 5, y),
                description=f"LED {i + 1} current-limit resistor",
            )

            # GPIO → resistor pin 1 → resistor pin 2 → LED anode (pin 1)
            pcb.net(f"LED_IND{i}", [(mcu, gpio_pins[i]), (res, "1")])
            pcb.net(f"LED_A{i}", [(res, "2"), (led, "1")])
            # LED cathode (pin 2) → GND
            pcb.power_net("GND", [(led, "2")])

            placed.append(led)

        self._log.append(f"Added {len(placed)} indicator LED(s) with resistors")
        return placed

    # ── Mounting Holes ───────────────────────────────────────────────────

    def _add_mounting_holes(
        self,
        pcb: PCBDesign,
        width: float,
        height: float,
    ) -> list[PlacedComponent]:
        """Place M3 mounting holes at the four corners of the board."""
        margin = 4.0  # mm from board edge
        positions = [
            (margin, margin),
            (width - margin, margin),
            (width - margin, height - margin),
            (margin, height - margin),
        ]
        holes: list[PlacedComponent] = []
        for x, y in positions:
            h = pcb.place(
                self._next_ref("H"), "MountingHole_M3", value="M3",
                pos=(x, y), description="M3 mounting hole",
            )
            holes.append(h)

        self._log.append("Added 4 M3 mounting holes at corners")
        return holes

    # ── Validate & Improve ───────────────────────────────────────────────

    def _validate_and_improve(self, pcb: PCBDesign) -> None:
        """Build a temporary board, validate, and fix critical issues.

        Runs up to 5 iterations.  In each iteration:
        * Out-of-bounds components -> increase board dimensions.
        * Overlapping components -> push apart by 3 mm along their
          offset direction.
        """
        from ..engines.design_validator import DesignValidator

        validator = DesignValidator()
        max_iterations = 5

        for iteration in range(max_iterations):
            board = pcb.build()
            result = validator.validate(board)

            # Collect critical-severity issues
            criticals = [i for i in result.issues if i.severity == "critical"]
            if not criticals:
                self._log.append(
                    f"Validation passed on iteration {iteration + 1}"
                )
                return

            self._log.append(
                f"Validation iteration {iteration + 1}: "
                f"{len(criticals)} critical issue(s)"
            )

            for issue in criticals:
                msg_lower = issue.message.lower()

                if "outside" in msg_lower or "boundaries" in msg_lower:
                    # Out-of-bounds -- grow board to fit bounding rects
                    for comp in board.components:
                        r = comp.bounding_rect()
                        if r.right > pcb.width:
                            pcb.width = r.right + 5
                        if r.bottom > pcb.height:
                            pcb.height = r.bottom + 5
                        if r.left < 0:
                            # Component extends past left edge — shift it
                            pc = self._find_placed(pcb, comp.reference)
                            if pc:
                                pc.position = (
                                    pc.position[0] + abs(r.left) + 3,
                                    pc.position[1],
                                )
                        if r.top < 0:
                            # Component extends past top edge — shift it
                            pc = self._find_placed(pcb, comp.reference)
                            if pc:
                                pc.position = (
                                    pc.position[0],
                                    pc.position[1] + abs(r.top) + 3,
                                )
                    self._log.append(
                        f"  Increased board to {pcb.width}x{pcb.height}mm"
                    )

                elif "overlap" in msg_lower:
                    refs = issue.component_refs
                    if len(refs) == 2:
                        # Find the placed components in the DSL list
                        pc1 = self._find_placed(pcb, refs[0])
                        pc2 = self._find_placed(pcb, refs[1])
                        if pc1 and pc2:
                            dx = pc1.position[0] - pc2.position[0]
                            dy = pc1.position[1] - pc2.position[1]
                            dist = math.hypot(dx, dy)
                            if dist < 0.01:
                                dx, dy, dist = 1.0, 0.0, 1.0
                            nx = dx / dist
                            ny = dy / dist
                            push = 3.0
                            pc1.position = (
                                pc1.position[0] + push * nx,
                                pc1.position[1] + push * ny,
                            )
                            pc2.position = (
                                pc2.position[0] - push * nx,
                                pc2.position[1] - push * ny,
                            )

        self._log.append(
            f"Validation finished after {max_iterations} iterations "
            f"(some issues may remain)"
        )

    @staticmethod
    def _find_placed(pcb: PCBDesign, ref: str) -> PlacedComponent | None:
        """Find a ``PlacedComponent`` in the DSL by reference designator."""
        for pc in pcb._components:
            if pc.reference == ref:
                return pc
        return None
