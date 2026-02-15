"""Reusable subcircuit building blocks for LLM-composed PCB designs.

Each subcircuit is a function that takes a ``PCBDesign`` instance, a
starting reference-designator number, a placement position, and optional
configuration parameters.  It places components, wires internal nets
(power and ground are connected immediately; signal nets are left for
the caller to cross-wire), and returns a dict mapping symbolic names to
``PlacedComponent`` objects so the caller can hook signals together.

Example usage::

    from ai_pcb_designer.ai.pcb_dsl import PCBDesign
    from ai_pcb_designer.ai.subcircuits import (
        usb_c_power, ldo_3v3, esp32_minimal, led_with_resistor,
    )

    pcb = PCBDesign("My Board", width=80, height=60)

    pwr  = usb_c_power(pcb, ref_start=1, pos=(40, 5))
    ldo  = ldo_3v3(pcb, ref_start=10, pos=(60, 10))
    mcu  = esp32_minimal(pcb, ref_start=20, pos=(40, 30))
    led1 = led_with_resistor(pcb, ref_start=50, pos=(70, 45))

    # Cross-wire: VBUS from USB to LDO input
    pcb.power_net("VBUS", [(pwr["usb"], "A4"), (ldo["ldo"], "1")])

    # Cross-wire: 3V3 from LDO output to MCU power
    pcb.power_net("3V3", [(ldo["ldo"], "3"), (mcu["esp32"], "2")])

    board = pcb.build()
"""

from __future__ import annotations

from .pcb_dsl import PCBDesign, PlacedComponent


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ref(prefix: str, start: int, offset: int = 0) -> str:
    """Generate a reference designator like ``R12`` from prefix, start, and offset."""
    return f"{prefix}{start + offset}"


# ---------------------------------------------------------------------------
# 1. USB-C Power Connector
# ---------------------------------------------------------------------------

def usb_c_power(
    pcb: PCBDesign,
    ref_start: int,
    pos: tuple[float, float],
) -> dict[str, PlacedComponent]:
    """USB Type-C connector with ESD-protection concept filter caps.

    Places a USB-C 16-pin connector with two decoupling / filter
    capacitors on the VBUS line.

    Internal nets wired:
        - ``GND`` (power) on connector GND pads and cap negative terminals
        - ``VBUS`` (power) on connector VBUS pads and cap positive terminals

    Returned keys:
        ``usb`` -- the USB-C connector (signal pads: A6/D+, A7/D-, B6/D+,
        B7/D-, A5/CC1, B5/CC2 are available for caller wiring)
        ``c_filter1`` -- first VBUS filter cap
        ``c_filter2`` -- second VBUS filter cap
    """
    x, y = pos

    usb = pcb.place(
        _ref("J", ref_start), "USB_C_16pin", value="USB-C",
        pos=(x, y), description="USB Type-C power connector",
    )
    c1 = pcb.place(
        _ref("C", ref_start, 1), "C_0603", value="100nF",
        pos=(x - 8, y + 9), description="VBUS filter cap 1",
    )
    c2 = pcb.place(
        _ref("C", ref_start, 2), "C_0603", value="4.7uF",
        pos=(x + 8, y + 9), description="VBUS filter cap 2",
    )

    # Power nets
    pcb.power_net("VBUS", [
        (usb, "A4"), (usb, "A9"),
        (usb, "B9"), (usb, "B4"),
        (c1, "1"), (c2, "1"),
    ])
    pcb.power_net("GND", [
        (usb, "A1"), (usb, "A12"),
        (usb, "B12"), (usb, "B1"),
        (c1, "2"), (c2, "2"),
    ])

    return {"usb": usb, "c_filter1": c1, "c_filter2": c2}


# ---------------------------------------------------------------------------
# 2. USB Micro-B Power Connector
# ---------------------------------------------------------------------------

def usb_micro_power(
    pcb: PCBDesign,
    ref_start: int,
    pos: tuple[float, float],
) -> dict[str, PlacedComponent]:
    """USB Micro-B connector with filter capacitors.

    Internal nets wired:
        - ``GND`` (power) on pin 5 and cap ground
        - ``VBUS`` (power) on pin 1 and cap VCC

    Returned keys:
        ``usb`` -- the Micro-B connector (pins 2/D-, 3/D+, 4/ID available)
        ``c_filter`` -- VBUS filter cap
    """
    x, y = pos

    usb = pcb.place(
        _ref("J", ref_start), "USB_Micro_B", value="USB-Micro",
        pos=(x, y), description="USB Micro-B power connector",
    )
    c1 = pcb.place(
        _ref("C", ref_start, 1), "C_0603", value="100nF",
        pos=(x + 7, y + 2), description="VBUS filter cap",
    )

    pcb.power_net("VBUS", [(usb, "1"), (c1, "1")])
    pcb.power_net("GND", [(usb, "5"), (c1, "2")])

    return {"usb": usb, "c_filter": c1}


# ---------------------------------------------------------------------------
# 3. LDO 3.3 V (AMS1117-3.3)
# ---------------------------------------------------------------------------

def ldo_3v3(
    pcb: PCBDesign,
    ref_start: int,
    pos: tuple[float, float],
) -> dict[str, PlacedComponent]:
    """AMS1117-3.3 LDO regulator with input and output decoupling caps.

    SOT-223 pinout: 1=input, 2=ground, 3=output.

    Internal nets wired:
        - ``VBUS`` (power) on LDO input (pin 1) and C_in positive
        - ``3V3`` (power) on LDO output (pin 3) and C_out positive
        - ``GND`` (power) on LDO ground (pin 2), C_in neg, C_out neg

    Returned keys:
        ``ldo`` -- the LDO regulator
        ``c_in`` -- input capacitor (10 uF)
        ``c_out`` -- output capacitor (22 uF)
    """
    x, y = pos

    ldo = pcb.place(
        _ref("U", ref_start), "SOT-223", value="AMS1117-3.3",
        pos=(x, y), description="3.3V LDO regulator",
    )
    c_in = pcb.place(
        _ref("C", ref_start, 1), "C_0805", value="10uF",
        pos=(x - 6, y + 5), description="LDO input capacitor",
    )
    c_out = pcb.place(
        _ref("C", ref_start, 2), "C_0805", value="22uF",
        pos=(x + 6, y + 5), description="LDO output capacitor",
    )

    pcb.power_net("VBUS", [(ldo, "1"), (c_in, "1")])
    pcb.power_net("3V3", [(ldo, "3"), (c_out, "1")])
    pcb.power_net("GND", [(ldo, "2"), (c_in, "2"), (c_out, "2")])

    return {"ldo": ldo, "c_in": c_in, "c_out": c_out}


# ---------------------------------------------------------------------------
# 4. LDO 5 V
# ---------------------------------------------------------------------------

def ldo_5v(
    pcb: PCBDesign,
    ref_start: int,
    pos: tuple[float, float],
) -> dict[str, PlacedComponent]:
    """5 V LDO regulator with input and output decoupling caps.

    SOT-223 pinout: 1=input, 2=ground, 3=output.

    Internal nets wired:
        - ``VIN`` (power) on LDO input (pin 1) and C_in positive
        - ``5V`` (power) on LDO output (pin 3) and C_out positive
        - ``GND`` (power) on LDO ground (pin 2), C_in neg, C_out neg

    Returned keys:
        ``ldo`` -- the LDO regulator
        ``c_in`` -- input capacitor (10 uF)
        ``c_out`` -- output capacitor (22 uF)
    """
    x, y = pos

    ldo = pcb.place(
        _ref("U", ref_start), "SOT-223", value="LDO-5V",
        pos=(x, y), description="5V LDO regulator",
    )
    c_in = pcb.place(
        _ref("C", ref_start, 1), "C_0805", value="10uF",
        pos=(x - 6, y + 5), description="LDO input capacitor",
    )
    c_out = pcb.place(
        _ref("C", ref_start, 2), "C_0805", value="22uF",
        pos=(x + 6, y + 5), description="LDO output capacitor",
    )

    pcb.power_net("VIN", [(ldo, "1"), (c_in, "1")])
    pcb.power_net("5V", [(ldo, "3"), (c_out, "1")])
    pcb.power_net("GND", [(ldo, "2"), (c_in, "2"), (c_out, "2")])

    return {"ldo": ldo, "c_in": c_in, "c_out": c_out}


# ---------------------------------------------------------------------------
# 5. Buck Converter (generic placeholder)
# ---------------------------------------------------------------------------

def buck_converter(
    pcb: PCBDesign,
    ref_start: int,
    pos: tuple[float, float],
) -> dict[str, PlacedComponent]:
    """Generic buck converter placeholder circuit.

    Uses a SOT-23-3 as the switching IC, an R_0805 as an inductor
    placeholder, and input/output capacitors.  This is a schematic-level
    placeholder -- the actual inductor footprint would be swapped during
    BOM finalization.

    SOT-23-3 pinout used here: 1=VIN, 2=GND, 3=SW (switch node).

    Internal nets wired:
        - ``VIN`` (power) on IC input and C_in positive
        - ``BUCK_OUT`` on C_out positive (caller connects to downstream rail)
        - ``GND`` (power) on IC ground, C_in neg, C_out neg
        - ``BUCK_SW`` (signal) between IC switch pin and inductor

    Returned keys:
        ``ic`` -- the buck converter IC (SOT-23-3)
        ``inductor`` -- inductor placeholder (R_0805)
        ``c_in`` -- input cap
        ``c_out`` -- output cap
    """
    x, y = pos

    ic = pcb.place(
        _ref("U", ref_start), "SOT-23-3", value="Buck-IC",
        pos=(x, y), description="Buck converter IC",
    )
    inductor = pcb.place(
        _ref("L", ref_start, 1), "R_0805", value="10uH",
        pos=(x + 6, y), description="Buck inductor placeholder",
    )
    c_in = pcb.place(
        _ref("C", ref_start, 2), "C_0805", value="10uF",
        pos=(x - 6, y + 4), description="Buck input capacitor",
    )
    c_out = pcb.place(
        _ref("C", ref_start, 3), "C_0805", value="22uF",
        pos=(x + 6, y + 4), description="Buck output capacitor",
    )

    # Power nets
    pcb.power_net("VIN", [(ic, "1"), (c_in, "1")])
    pcb.power_net("GND", [(ic, "2"), (c_in, "2"), (c_out, "2")])

    # Internal signal: switch node to inductor
    pcb.net("BUCK_SW", [(ic, "3"), (inductor, "1")])
    # Inductor output to output cap
    pcb.net("BUCK_OUT", [(inductor, "2"), (c_out, "1")])

    return {"ic": ic, "inductor": inductor, "c_in": c_in, "c_out": c_out}


# ---------------------------------------------------------------------------
# 6. ESP32 Minimal
# ---------------------------------------------------------------------------

def esp32_minimal(
    pcb: PCBDesign,
    ref_start: int,
    pos: tuple[float, float],
) -> dict[str, PlacedComponent]:
    """ESP32-WROOM-32 module with bypass caps, EN/IO0 pull-ups, and buttons.

    Provides a ready-to-run ESP32 subcircuit.  Signal GPIOs are not
    wired -- the caller picks which ones to use.

    Internal nets wired:
        - ``3V3`` (power) on ESP32 pin 2, bypass caps, pull-up tops
        - ``GND`` (power) on ESP32 pins 1/15/39, bypass caps, button
          commons
        - ``EN`` (signal) on ESP32 pin 3, R_en, reset button
        - ``IO0`` (signal) on ESP32 pin 25, R_io0, boot button

    Returned keys:
        ``esp32`` -- the ESP32 module (all GPIO pins available)
        ``c_byp1``, ``c_byp2`` -- bypass capacitors
        ``r_en`` -- EN pull-up resistor
        ``r_io0`` -- IO0 pull-up resistor
        ``btn_reset`` -- reset push-button
        ``btn_boot`` -- boot / IO0 push-button
    """
    x, y = pos

    esp32 = pcb.place(
        _ref("U", ref_start), "ESP32-WROOM-32", value="ESP32-WROOM-32",
        pos=(x, y), description="ESP32 MCU module",
    )
    c_byp1 = pcb.place(
        _ref("C", ref_start, 1), "C_0603", value="100nF",
        pos=(x - 12, y + 16), description="ESP32 bypass cap 1",
    )
    c_byp2 = pcb.place(
        _ref("C", ref_start, 2), "C_0603", value="100nF",
        pos=(x + 12, y + 16), description="ESP32 bypass cap 2",
    )
    r_en = pcb.place(
        _ref("R", ref_start, 3), "R_0603", value="10k",
        pos=(x - 14, y + 12), description="EN pull-up resistor",
    )
    r_io0 = pcb.place(
        _ref("R", ref_start, 4), "R_0603", value="10k",
        pos=(x + 14, y + 12), description="IO0 pull-up resistor",
    )
    btn_reset = pcb.place(
        _ref("SW", ref_start, 5), "SW_Push_6mm", value="RESET",
        pos=(x - 20, y + 12), description="Reset button",
    )
    btn_boot = pcb.place(
        _ref("SW", ref_start, 6), "SW_Push_6mm", value="BOOT",
        pos=(x + 20, y + 12), description="Boot / IO0 button",
    )

    # 3V3 power rail
    pcb.power_net("3V3", [
        (esp32, "2"),
        (c_byp1, "1"), (c_byp2, "1"),
        (r_en, "1"), (r_io0, "1"),
    ])

    # GND power rail
    pcb.power_net("GND", [
        (esp32, "1"), (esp32, "15"), (esp32, "39"),
        (c_byp1, "2"), (c_byp2, "2"),
        (btn_reset, "2"), (btn_boot, "2"),
    ])

    # EN signal
    pcb.net("EN", [(esp32, "3"), (r_en, "2"), (btn_reset, "1")])

    # IO0 signal
    pcb.net("IO0", [(esp32, "25"), (r_io0, "2"), (btn_boot, "1")])

    return {
        "esp32": esp32,
        "c_byp1": c_byp1,
        "c_byp2": c_byp2,
        "r_en": r_en,
        "r_io0": r_io0,
        "btn_reset": btn_reset,
        "btn_boot": btn_boot,
    }


# ---------------------------------------------------------------------------
# 7. STM32 Minimal (QFP-48 placeholder)
# ---------------------------------------------------------------------------

def stm32_minimal(
    pcb: PCBDesign,
    ref_start: int,
    pos: tuple[float, float],
) -> dict[str, PlacedComponent]:
    """STM32 in a QFP-48-like placeholder with bypass caps and reset circuit.

    Since a true QFP-48 footprint is not in the registry, this uses
    the ESP32-WROOM-32 footprint as a large-IC placeholder.  The pin
    mapping is symbolic -- this is intended as a schematic-level block
    that demonstrates the subcircuit pattern.  Swap the footprint once
    a QFP-48 is added to the library.

    Symbolic pin assignments (on the placeholder footprint):
        - Pin 1 = VBAT, Pin 2 = 3V3 (VDD), Pin 15 = GND (VSS)
        - Pin 3 = NRST
        - Remaining pins are GPIO (available for caller wiring)

    Internal nets wired:
        - ``3V3`` (power) on VDD pin, bypass caps, pull-up R top
        - ``GND`` (power) on VSS pin, bypass caps, button common
        - ``NRST`` (signal) on pin 3, reset pull-up, reset button

    Returned keys:
        ``mcu`` -- the STM32 placeholder
        ``c_byp1``, ``c_byp2``, ``c_byp3`` -- bypass capacitors
        ``r_reset`` -- NRST pull-up resistor
        ``btn_reset`` -- reset button
        ``c_reset`` -- NRST debounce capacitor
    """
    x, y = pos

    # Using ESP32-WROOM-32 as a large-IC placeholder for QFP-48
    mcu = pcb.place(
        _ref("U", ref_start), "ESP32-WROOM-32", value="STM32F103C8",
        pos=(x, y), description="STM32 MCU (QFP-48 placeholder)",
    )

    # Three bypass caps (one per VDD/VDDA pair, typical for STM32)
    c_byp1 = pcb.place(
        _ref("C", ref_start, 1), "C_0603", value="100nF",
        pos=(x - 12, y + 16), description="STM32 VDD bypass cap 1",
    )
    c_byp2 = pcb.place(
        _ref("C", ref_start, 2), "C_0603", value="100nF",
        pos=(x + 12, y + 16), description="STM32 VDD bypass cap 2",
    )
    c_byp3 = pcb.place(
        _ref("C", ref_start, 3), "C_0603", value="4.7uF",
        pos=(x, y + 18), description="STM32 VDDA bulk cap",
    )

    # Reset circuit
    r_reset = pcb.place(
        _ref("R", ref_start, 4), "R_0603", value="10k",
        pos=(x - 14, y + 12), description="NRST pull-up resistor",
    )
    c_reset = pcb.place(
        _ref("C", ref_start, 5), "C_0603", value="100nF",
        pos=(x - 14, y + 15), description="NRST debounce capacitor",
    )
    btn_reset = pcb.place(
        _ref("SW", ref_start, 6), "SW_Push_6mm", value="RESET",
        pos=(x - 22, y + 12), description="Reset button",
    )

    # Power nets
    pcb.power_net("3V3", [
        (mcu, "2"),  # VDD
        (c_byp1, "1"), (c_byp2, "1"), (c_byp3, "1"),
        (r_reset, "1"),
    ])
    pcb.power_net("GND", [
        (mcu, "15"),  # VSS
        (c_byp1, "2"), (c_byp2, "2"), (c_byp3, "2"),
        (c_reset, "2"),
        (btn_reset, "2"),
    ])

    # Reset signal
    pcb.net("NRST", [
        (mcu, "3"), (r_reset, "2"), (c_reset, "1"), (btn_reset, "1"),
    ])

    return {
        "mcu": mcu,
        "c_byp1": c_byp1,
        "c_byp2": c_byp2,
        "c_byp3": c_byp3,
        "r_reset": r_reset,
        "c_reset": c_reset,
        "btn_reset": btn_reset,
    }


# ---------------------------------------------------------------------------
# 8. I2C Pull-ups
# ---------------------------------------------------------------------------

def i2c_pullups(
    pcb: PCBDesign,
    ref_start: int,
    pos: tuple[float, float],
) -> dict[str, PlacedComponent]:
    """Pull-up resistors for an I2C bus (SDA + SCL lines).

    Both resistors have one end on ``3V3`` (power net).  The other ends
    are left as signal pins (``SDA`` pin 2 on r_sda, ``SCL`` pin 2 on
    r_scl) for the caller to wire to the MCU and peripherals.

    Internal nets wired:
        - ``3V3`` (power) on pin 1 of both resistors

    Returned keys:
        ``r_sda`` -- SDA pull-up (pin 2 = SDA signal)
        ``r_scl`` -- SCL pull-up (pin 2 = SCL signal)
    """
    x, y = pos

    r_sda = pcb.place(
        _ref("R", ref_start), "R_0603", value="4.7k",
        pos=(x, y), description="I2C SDA pull-up",
    )
    r_scl = pcb.place(
        _ref("R", ref_start, 1), "R_0603", value="4.7k",
        pos=(x + 4, y), description="I2C SCL pull-up",
    )

    pcb.power_net("3V3", [(r_sda, "1"), (r_scl, "1")])

    return {"r_sda": r_sda, "r_scl": r_scl}


# ---------------------------------------------------------------------------
# 9. UART Header
# ---------------------------------------------------------------------------

def uart_header(
    pcb: PCBDesign,
    ref_start: int,
    pos: tuple[float, float],
) -> dict[str, PlacedComponent]:
    """1x04 pin header for UART: VCC, GND, TX, RX.

    Pin-out (matching common FTDI cable order):
        1 = VCC, 2 = GND, 3 = TX, 4 = RX

    Internal nets wired:
        - ``3V3`` (power) on pin 1
        - ``GND`` (power) on pin 2

    Returned keys:
        ``header`` -- the 1x04 header (pins 3/TX, 4/RX for caller)
    """
    x, y = pos

    header = pcb.place(
        _ref("J", ref_start), "PinHeader_1x04", value="UART",
        pos=(x, y), description="UART header (VCC/GND/TX/RX)",
    )

    pcb.power_net("3V3", [(header, "1")])
    pcb.power_net("GND", [(header, "2")])

    return {"header": header}


# ---------------------------------------------------------------------------
# 10. SPI Header
# ---------------------------------------------------------------------------

def spi_header(
    pcb: PCBDesign,
    ref_start: int,
    pos: tuple[float, float],
) -> dict[str, PlacedComponent]:
    """1x06 pin header for SPI: VCC, GND, MOSI, MISO, SCK, CS.

    Pin-out:
        1 = VCC, 2 = GND, 3 = MOSI, 4 = MISO, 5 = SCK, 6 = CS

    Internal nets wired:
        - ``3V3`` (power) on pin 1
        - ``GND`` (power) on pin 2

    Returned keys:
        ``header`` -- the 1x06 header (pins 3-6 for caller wiring)
    """
    x, y = pos

    header = pcb.place(
        _ref("J", ref_start), "PinHeader_1x06", value="SPI",
        pos=(x, y), description="SPI header (VCC/GND/MOSI/MISO/SCK/CS)",
    )

    pcb.power_net("3V3", [(header, "1")])
    pcb.power_net("GND", [(header, "2")])

    return {"header": header}


# ---------------------------------------------------------------------------
# 11. Debug Header
# ---------------------------------------------------------------------------

def debug_header(
    pcb: PCBDesign,
    ref_start: int,
    pos: tuple[float, float],
) -> dict[str, PlacedComponent]:
    """1x06 debug / programming header: 3V3, GND, TXD, RXD, IO0, EN.

    Pin-out:
        1 = 3V3, 2 = GND, 3 = TXD, 4 = RXD, 5 = IO0, 6 = EN

    Internal nets wired:
        - ``3V3`` (power) on pin 1
        - ``GND`` (power) on pin 2

    Returned keys:
        ``header`` -- the 1x06 header (pins 3-6 for caller wiring)
    """
    x, y = pos

    header = pcb.place(
        _ref("J", ref_start), "PinHeader_1x06", value="DEBUG",
        pos=(x, y), description="Debug header (3V3/GND/TXD/RXD/IO0/EN)",
    )

    pcb.power_net("3V3", [(header, "1")])
    pcb.power_net("GND", [(header, "2")])

    return {"header": header}


# ---------------------------------------------------------------------------
# 12. LED with Current-Limiting Resistor
# ---------------------------------------------------------------------------

def led_with_resistor(
    pcb: PCBDesign,
    ref_start: int,
    pos: tuple[float, float],
    color: str = "green",
) -> dict[str, PlacedComponent]:
    """Single indicator LED with a current-limiting resistor.

    The resistor value is chosen based on the LED color to target
    roughly 10-15 mA at 3.3 V.

    Wiring: signal_in -> R pin 1 -> R pin 2 -> LED anode (pin 1) ->
    LED cathode (pin 2) -> GND.

    Internal nets wired:
        - ``GND`` (power) on LED cathode (pin 2)
        - ``LED_Rxx_A`` (signal) between R pin 2 and LED anode

    The caller must wire a GPIO or signal to R pin 1 (the ``resistor``
    component).

    Returned keys:
        ``resistor`` -- current-limiting resistor (pin 1 = signal input)
        ``led`` -- the LED (pin 2 = GND, already wired)
    """
    x, y = pos

    # Resistor value depends on LED forward voltage
    color_lower = color.lower()
    resistor_values = {
        "red": "150",
        "green": "330",
        "blue": "100",
        "yellow": "220",
        "white": "100",
        "orange": "180",
    }
    r_val = resistor_values.get(color_lower, "330")

    resistor = pcb.place(
        _ref("R", ref_start), "R_0603", value=r_val,
        pos=(x - 3, y), description=f"{color} LED current-limit resistor",
    )
    led = pcb.place(
        _ref("D", ref_start, 1), "LED_0603", value=f"LED_{color}",
        pos=(x + 3, y), description=f"{color} indicator LED",
    )

    # R output -> LED anode
    led_net_name = f"LED_{_ref('R', ref_start)}_A"
    pcb.net(led_net_name, [(resistor, "2"), (led, "1")])

    # LED cathode -> GND
    pcb.power_net("GND", [(led, "2")])

    return {"resistor": resistor, "led": led}


# ---------------------------------------------------------------------------
# 13. Button with Pull-up and Debounce Cap
# ---------------------------------------------------------------------------

def button_with_pullup(
    pcb: PCBDesign,
    ref_start: int,
    pos: tuple[float, float],
) -> dict[str, PlacedComponent]:
    """Pushbutton with pull-up resistor and debounce capacitor.

    When not pressed the signal pin reads HIGH (pulled to 3V3).
    When pressed the signal pin is shorted to GND (active-low).
    The debounce capacitor filters contact bounce.

    Wiring: 3V3 -> R pin 1 -> R pin 2 / BTN pin 1 / C pin 1 (signal
    node) and BTN pin 2 -> GND, C pin 2 -> GND.

    Internal nets wired:
        - ``3V3`` (power) on R pin 1
        - ``GND`` (power) on button pin 2 and cap pin 2
        - ``BTN_SWxx`` (signal) on R pin 2, button pin 1, cap pin 1

    The caller reads the signal from ``btn`` pin 1 or ``resistor`` pin 2
    (they are the same net).

    Returned keys:
        ``btn`` -- the push-button (pin 1 = signal node)
        ``resistor`` -- pull-up resistor (pin 2 = signal node)
        ``cap`` -- debounce capacitor (pin 1 = signal node)
    """
    x, y = pos

    btn = pcb.place(
        _ref("SW", ref_start), "SW_Push_6mm", value="BTN",
        pos=(x, y), description="Push button",
    )
    resistor = pcb.place(
        _ref("R", ref_start, 1), "R_0603", value="10k",
        pos=(x + 7, y - 2), description="Button pull-up resistor",
    )
    cap = pcb.place(
        _ref("C", ref_start, 2), "C_0603", value="100nF",
        pos=(x + 7, y + 2), description="Button debounce capacitor",
    )

    # Signal node
    sig_name = f"BTN_{_ref('SW', ref_start)}"
    pcb.net(sig_name, [(btn, "1"), (resistor, "2"), (cap, "1")])

    # Power nets
    pcb.power_net("3V3", [(resistor, "1")])
    pcb.power_net("GND", [(btn, "2"), (cap, "2")])

    return {"btn": btn, "resistor": resistor, "cap": cap}


# ---------------------------------------------------------------------------
# 14. Voltage Divider
# ---------------------------------------------------------------------------

def voltage_divider(
    pcb: PCBDesign,
    ref_start: int,
    pos: tuple[float, float],
    r_top: str = "10k",
    r_bottom: str = "10k",
) -> dict[str, PlacedComponent]:
    """Two-resistor voltage divider.

    Schematic::

        VIN ── R_top pin 1 ── R_top pin 2 ── MID ── R_bot pin 1
                                                       ── R_bot pin 2 ── GND

    The midpoint is a signal net (``VDIV_MID_xx``) that the caller can
    connect to an ADC or comparator input.

    Internal nets wired:
        - ``GND`` (power) on R_bottom pin 2
        - ``VDIV_MID_xx`` (signal) between R_top pin 2 and R_bottom pin 1

    The caller wires the input voltage to R_top pin 1.

    Returned keys:
        ``r_top`` -- top resistor (pin 1 = high-side input)
        ``r_bottom`` -- bottom resistor (pin 2 = GND)
    """
    x, y = pos

    r_t = pcb.place(
        _ref("R", ref_start), "R_0603", value=r_top,
        pos=(x, y - 2), description="Voltage divider top resistor",
    )
    r_b = pcb.place(
        _ref("R", ref_start, 1), "R_0603", value=r_bottom,
        pos=(x, y + 2), description="Voltage divider bottom resistor",
    )

    # Midpoint signal net
    mid_name = f"VDIV_MID_{_ref('R', ref_start)}"
    pcb.net(mid_name, [(r_t, "2"), (r_b, "1")])

    # Bottom to GND
    pcb.power_net("GND", [(r_b, "2")])

    return {"r_top": r_t, "r_bottom": r_b}


# ---------------------------------------------------------------------------
# 15. Single Decoupling Capacitor
# ---------------------------------------------------------------------------

def decoupling_cap(
    pcb: PCBDesign,
    ref_start: int,
    pos: tuple[float, float],
    value: str = "100nF",
) -> dict[str, PlacedComponent]:
    """Single decoupling capacitor between a power rail and GND.

    Internal nets wired:
        - ``GND`` (power) on pin 2

    Pin 1 (VCC side) is left for the caller to wire to the
    appropriate power net.

    Returned keys:
        ``cap`` -- the decoupling capacitor (pin 1 = VCC, pin 2 = GND)
    """
    x, y = pos

    cap = pcb.place(
        _ref("C", ref_start), "C_0603", value=value,
        pos=(x, y), description=f"{value} decoupling capacitor",
    )

    pcb.power_net("GND", [(cap, "2")])

    return {"cap": cap}


# ---------------------------------------------------------------------------
# 16. Mounting Holes at Board Corners
# ---------------------------------------------------------------------------

def mounting_holes_corners(
    pcb: PCBDesign,
    ref_start: int,
    board_width: float,
    board_height: float,
) -> dict[str, PlacedComponent]:
    """Mounting holes at all four board corners.

    Placement rules:
    - Inset 5 mm from each edge (enough for M3 screw head + washer)
    - Always places 4 holes (all four corners)

    Returned keys:
        ``hole_tl`` -- top-left
        ``hole_tr`` -- top-right
        ``hole_br`` -- bottom-right
        ``hole_bl`` -- bottom-left
    """
    margin = 5.0  # 5mm inset for screw head clearance

    comps: dict[str, PlacedComponent] = {}
    idx = 0

    h_tl = pcb.place(
        _ref("H", ref_start, idx), "MountingHole_M3", value="M3",
        pos=(margin, margin), description="M3 mounting hole",
    )
    comps["hole_tl"] = h_tl
    idx += 1

    h_tr = pcb.place(
        _ref("H", ref_start, idx), "MountingHole_M3", value="M3",
        pos=(board_width - margin, margin),
        description="M3 mounting hole",
    )
    comps["hole_tr"] = h_tr
    idx += 1

    h_br = pcb.place(
        _ref("H", ref_start, idx), "MountingHole_M3", value="M3",
        pos=(board_width - margin, board_height - margin),
        description="M3 mounting hole",
    )
    comps["hole_br"] = h_br
    idx += 1

    h_bl = pcb.place(
        _ref("H", ref_start, idx), "MountingHole_M3", value="M3",
        pos=(margin, board_height - margin),
        description="M3 mounting hole",
    )
    comps["hole_bl"] = h_bl

    return comps


# ---------------------------------------------------------------------------
# 17. NeoPixel (WS2812B) Strip
# ---------------------------------------------------------------------------

def neopixel_strip(
    pcb: PCBDesign,
    ref_start: int,
    pos: tuple[float, float],
    count: int = 8,
    pitch: float = 10.0,
) -> dict[str, PlacedComponent]:
    """Horizontal strip of WS2812B addressable LEDs.

    LEDs are placed in a line from left to right, each separated by
    ``pitch`` mm.  Data is daisy-chained: DIN of LED[0] is the signal
    input, DOUT[n] -> DIN[n+1].

    WS2812B pinout: 1=VDD, 2=DOUT, 3=GND, 4=DIN.

    Internal nets wired:
        - ``VCC`` (power) on every LED pin 1 (VDD)
        - ``GND`` (power) on every LED pin 3
        - ``NEOPIXEL_Dn`` (signal) for each DOUT->DIN chain link

    The caller wires a data signal to ``leds[0]`` pin 4 (DIN) and
    optionally reads ``leds[-1]`` pin 2 (DOUT) for further chaining.

    Returned keys:
        ``leds`` -- list of PlacedComponent (index 0 = first LED)
        ``led_0`` .. ``led_N`` -- individual LEDs by index
        ``c_bulk`` -- bulk decoupling cap for the strip
    """
    x, y = pos
    comps: dict[str, PlacedComponent] = {}

    leds: list[PlacedComponent] = []
    vcc_pads: list[tuple] = []
    gnd_pads: list[tuple] = []

    for i in range(count):
        lx = x + i * pitch
        led = pcb.place(
            _ref("D", ref_start, i), "WS2812B", value="WS2812B",
            pos=(lx, y), description=f"NeoPixel LED {i}",
        )
        leds.append(led)
        comps[f"led_{i}"] = led
        vcc_pads.append((led, "1"))
        gnd_pads.append((led, "3"))

    # Bulk decoupling cap at the end of the strip
    c_bulk = pcb.place(
        _ref("C", ref_start, count), "C_0805", value="100uF",
        pos=(x + count * pitch, y), description="NeoPixel strip bulk cap",
    )
    vcc_pads.append((c_bulk, "1"))
    gnd_pads.append((c_bulk, "2"))

    pcb.power_net("VCC", vcc_pads)
    pcb.power_net("GND", gnd_pads)

    # Data chain
    for i in range(len(leds) - 1):
        pcb.net(
            f"NEOPIXEL_D{ref_start}_{i}",
            [(leds[i], "2"), (leds[i + 1], "4")],
        )

    comps["c_bulk"] = c_bulk
    return comps


# ---------------------------------------------------------------------------
# 18. Crystal Oscillator with Load Capacitors
# ---------------------------------------------------------------------------

def crystal_oscillator(
    pcb: PCBDesign,
    ref_start: int,
    pos: tuple[float, float],
) -> dict[str, PlacedComponent]:
    """Crystal oscillator with two load capacitors.

    Uses an R_0603 footprint as a crystal placeholder (two-pad passive
    component with the same footprint).  Two small-value capacitors
    connect each crystal leg to GND.

    Internal nets wired:
        - ``GND`` (power) on both load-cap pin 2
        - ``XTAL_IN`` (signal) crystal pin 1 + C1 pin 1
        - ``XTAL_OUT`` (signal) crystal pin 2 + C2 pin 1

    The caller wires ``XTAL_IN`` and ``XTAL_OUT`` to the MCU oscillator
    pins.

    Returned keys:
        ``crystal`` -- the crystal (R_0603 placeholder)
        ``c_load1`` -- load capacitor on XTAL_IN side
        ``c_load2`` -- load capacitor on XTAL_OUT side
    """
    x, y = pos

    crystal = pcb.place(
        _ref("Y", ref_start), "R_0603", value="8MHz",
        pos=(x, y), description="Crystal oscillator (placeholder)",
    )
    c_load1 = pcb.place(
        _ref("C", ref_start, 1), "C_0603", value="20pF",
        pos=(x - 4, y + 3), description="Crystal load capacitor 1",
    )
    c_load2 = pcb.place(
        _ref("C", ref_start, 2), "C_0603", value="20pF",
        pos=(x + 4, y + 3), description="Crystal load capacitor 2",
    )

    # Signal nets
    pcb.net("XTAL_IN", [(crystal, "1"), (c_load1, "1")])
    pcb.net("XTAL_OUT", [(crystal, "2"), (c_load2, "1")])

    # Load caps to GND
    pcb.power_net("GND", [(c_load1, "2"), (c_load2, "2")])

    return {"crystal": crystal, "c_load1": c_load1, "c_load2": c_load2}


# ---------------------------------------------------------------------------
# 19. H-Bridge (Dual Half-Bridge)
# ---------------------------------------------------------------------------

def h_bridge(
    pcb: PCBDesign,
    ref_start: int,
    pos: tuple[float, float],
) -> dict[str, PlacedComponent]:
    """Dual half-bridge using four SOT-23-3 MOSFETs and flyback diodes.

    This creates a full H-bridge for driving a DC motor or similar load.
    LED_0805 components are used as flyback-diode placeholders (same
    two-pad footprint; pin 1 = anode, pin 2 = cathode).

    SOT-23-3 pinout used: 1=gate, 2=source, 3=drain.

    Topology (one half-bridge per side)::

        VCC ── Q_high drain ── Q_high source ──┬── MOTOR_x
               Q_high gate = CTRL_xH           │
                                                └── Q_low drain
                                                    Q_low source ── GND
                                                    Q_low gate = CTRL_xL

    Internal nets wired:
        - ``VCC`` (power) on high-side MOSFET drains (pin 3)
        - ``GND`` (power) on low-side MOSFET sources (pin 2)
        - ``MOTOR_A`` (signal) midpoint of half-bridge A
        - ``MOTOR_B`` (signal) midpoint of half-bridge B

    Gate signals (``CTRL_AH``, ``CTRL_AL``, ``CTRL_BH``, ``CTRL_BL``)
    are left for the caller to wire to the MCU.

    Returned keys:
        ``q_ah``, ``q_al`` -- half-bridge A MOSFETs (high, low)
        ``q_bh``, ``q_bl`` -- half-bridge B MOSFETs (high, low)
        ``d_ah``, ``d_al``, ``d_bh``, ``d_bl`` -- flyback diodes
    """
    x, y = pos

    # Half-bridge A (left)
    q_ah = pcb.place(
        _ref("Q", ref_start, 0), "SOT-23-3", value="NMOS",
        pos=(x - 8, y - 5), description="H-bridge A high-side MOSFET",
    )
    q_al = pcb.place(
        _ref("Q", ref_start, 1), "SOT-23-3", value="NMOS",
        pos=(x - 8, y + 5), description="H-bridge A low-side MOSFET",
    )
    d_ah = pcb.place(
        _ref("D", ref_start, 2), "LED_0805", value="Diode",
        pos=(x - 4, y - 5), description="Flyback diode A high-side",
    )
    d_al = pcb.place(
        _ref("D", ref_start, 3), "LED_0805", value="Diode",
        pos=(x - 4, y + 5), description="Flyback diode A low-side",
    )

    # Half-bridge B (right)
    q_bh = pcb.place(
        _ref("Q", ref_start, 4), "SOT-23-3", value="NMOS",
        pos=(x + 8, y - 5), description="H-bridge B high-side MOSFET",
    )
    q_bl = pcb.place(
        _ref("Q", ref_start, 5), "SOT-23-3", value="NMOS",
        pos=(x + 8, y + 5), description="H-bridge B low-side MOSFET",
    )
    d_bh = pcb.place(
        _ref("D", ref_start, 6), "LED_0805", value="Diode",
        pos=(x + 4, y - 5), description="Flyback diode B high-side",
    )
    d_bl = pcb.place(
        _ref("D", ref_start, 7), "LED_0805", value="Diode",
        pos=(x + 4, y + 5), description="Flyback diode B low-side",
    )

    # Power nets
    pcb.power_net("VCC", [
        (q_ah, "3"), (q_bh, "3"),       # High-side drains
        (d_ah, "2"), (d_bh, "2"),        # Diode cathodes to VCC
    ])
    pcb.power_net("GND", [
        (q_al, "2"), (q_bl, "2"),        # Low-side sources
        (d_al, "1"), (d_bl, "1"),        # Diode anodes from GND side
    ])

    # Motor midpoints (high-side source to low-side drain)
    pcb.net("MOTOR_A", [
        (q_ah, "2"), (q_al, "3"),        # High source -> Low drain
        (d_ah, "1"), (d_al, "2"),        # Diode connections
    ])
    pcb.net("MOTOR_B", [
        (q_bh, "2"), (q_bl, "3"),
        (d_bh, "1"), (d_bl, "2"),
    ])

    return {
        "q_ah": q_ah, "q_al": q_al,
        "q_bh": q_bh, "q_bl": q_bl,
        "d_ah": d_ah, "d_al": d_al,
        "d_bh": d_bh, "d_bl": d_bl,
    }


# ---------------------------------------------------------------------------
# 20. Barrel Jack Power
# ---------------------------------------------------------------------------

def barrel_jack_power(
    pcb: PCBDesign,
    ref_start: int,
    pos: tuple[float, float],
) -> dict[str, PlacedComponent]:
    """Barrel jack with polarity-protection diode and input filter cap.

    The polarity-protection diode prevents damage from reversed-polarity
    input.  An LED_0805 footprint is used as a diode placeholder
    (pin 1 = anode, pin 2 = cathode).

    Barrel jack pinout: 1=tip/+, 2=sleeve/-, 3=switch (NC when plugged).

    Wiring::

        Barrel tip (pin 1) -> Diode anode (pin 1) -> Diode cathode
        (pin 2) -> VIN net + Cap pin 1
        Barrel sleeve (pin 2) -> GND + Cap pin 2

    Internal nets wired:
        - ``VIN`` (power) on diode cathode and cap pin 1
        - ``GND`` (power) on barrel sleeve (pin 2) and cap pin 2
        - ``JACK_TIP`` (signal) between barrel tip (pin 1) and diode
          anode (pin 1)

    Returned keys:
        ``jack`` -- the barrel jack connector
        ``diode`` -- polarity protection diode (LED_0805 placeholder)
        ``c_filter`` -- input filter capacitor
    """
    x, y = pos

    jack = pcb.place(
        _ref("J", ref_start), "BarrelJack_DC", value="Barrel_Jack",
        pos=(x, y), description="DC barrel jack power connector",
    )
    diode = pcb.place(
        _ref("D", ref_start, 1), "SOD-123", value="1N5819",
        pos=(x + 6, y), description="Polarity protection Schottky diode",
    )
    c_filter = pcb.place(
        _ref("C", ref_start, 2), "C_0805", value="100uF",
        pos=(x + 6, y + 4), description="Input filter capacitor",
    )

    # Barrel tip to diode anode
    pcb.net("JACK_TIP", [(jack, "1"), (diode, "A")])

    # Diode cathode to VIN rail
    pcb.power_net("VIN", [(diode, "K"), (c_filter, "1")])

    # Barrel sleeve and cap to GND
    pcb.power_net("GND", [(jack, "2"), (c_filter, "2")])

    return {"jack": jack, "diode": diode, "c_filter": c_filter}


# ---------------------------------------------------------------------------
# 21. Relay Driver
# ---------------------------------------------------------------------------

def relay_driver(
    pcb: PCBDesign,
    ref_start: int,
    pos: tuple[float, float],
    gpio_net: str = "RELAY_CTRL",
) -> dict[str, PlacedComponent]:
    """Relay with NPN transistor driver and flyback diode.

    Drives an SPDT relay from a GPIO pin via a SOT-23-3 NPN transistor.
    Includes a flyback diode across the coil for back-EMF protection
    and a base resistor for the transistor.

    Relay pinout: 1=coil+, 2=coil-, 3=COM, 4=NO, 5=NC.

    Internal nets wired:
        - ``5V`` or ``VBUS`` (power) on relay coil+
        - ``GND`` (power) on transistor emitter
        - ``gpio_net`` (signal) on base resistor

    Returned keys:
        ``relay``, ``transistor``, ``diode``, ``r_base``
    """
    x, y = pos

    relay = pcb.place(
        _ref("K", ref_start), "Relay_SPDT", value="SRD-05VDC",
        pos=(x, y), description="5V SPDT relay",
    )
    transistor = pcb.place(
        _ref("Q", ref_start, 1), "SOT-23-3", value="2N2222",
        pos=(x, y + 12), description="NPN relay driver",
    )
    diode = pcb.place(
        _ref("D", ref_start, 2), "SOD-123", value="1N4148",
        pos=(x + 8, y), description="Flyback diode",
    )
    r_base = pcb.place(
        _ref("R", ref_start, 3), "R_0603", value="1k",
        pos=(x - 3, y + 12), description="Base resistor",
    )

    # Coil+ to supply, coil- to transistor collector
    pcb.power_net("VBUS", [(relay, "1"), (diode, "K")])
    pcb.net("RELAY_COIL", [(relay, "2"), (transistor, "3"), (diode, "A")])

    # Transistor emitter to GND
    pcb.power_net("GND", [(transistor, "2")])

    # GPIO drives base through resistor
    pcb.net(gpio_net, [(r_base, "1")])
    pcb.net(f"{gpio_net}_BASE", [(r_base, "2"), (transistor, "1")])

    return {
        "relay": relay, "transistor": transistor,
        "diode": diode, "r_base": r_base,
    }


# ---------------------------------------------------------------------------
# 22. I2C Sensor Breakout
# ---------------------------------------------------------------------------

def i2c_sensor_breakout(
    pcb: PCBDesign,
    ref_start: int,
    pos: tuple[float, float],
    sensor_name: str = "BME280",
    with_pullups: bool = True,
) -> dict[str, PlacedComponent]:
    """Generic I2C sensor breakout header with optional pull-ups.

    A 4-pin header (VCC, GND, SDA, SCL) for connecting any I2C
    sensor module.  Optionally adds 4.7k pull-up resistors for
    SDA and SCL.

    Internal nets wired:
        - ``3V3`` (power) on header pin 1 and pull-up tops
        - ``GND`` (power) on header pin 2
        - ``I2C_SDA``, ``I2C_SCL`` (signal) on header pins 3-4

    Returned keys:
        ``header``, and optionally ``r_sda``, ``r_scl``
    """
    x, y = pos

    header = pcb.place(
        _ref("J", ref_start), "Sensor_I2C_4pin", value=sensor_name,
        pos=(x, y), description=f"I2C sensor header ({sensor_name})",
    )

    result: dict[str, PlacedComponent] = {"header": header}

    pcb.power_net("3V3", [(header, "1")])
    pcb.power_net("GND", [(header, "2")])

    sda_pads: list = [(header, "3")]
    scl_pads: list = [(header, "4")]

    if with_pullups:
        r_sda = pcb.place(
            _ref("R", ref_start, 1), "R_0603", value="4.7k",
            pos=(x + 4, y), description="I2C SDA pull-up",
        )
        r_scl = pcb.place(
            _ref("R", ref_start, 2), "R_0603", value="4.7k",
            pos=(x + 4, y + 3), description="I2C SCL pull-up",
        )
        pcb.power_net("3V3", [(r_sda, "1"), (r_scl, "1")])
        sda_pads.append((r_sda, "2"))
        scl_pads.append((r_scl, "2"))
        result["r_sda"] = r_sda
        result["r_scl"] = r_scl

    pcb.net("I2C_SDA", sda_pads)
    pcb.net("I2C_SCL", scl_pads)

    return result


# ---------------------------------------------------------------------------
# 23. SPI Sensor Breakout
# ---------------------------------------------------------------------------

def spi_sensor_breakout(
    pcb: PCBDesign,
    ref_start: int,
    pos: tuple[float, float],
    sensor_name: str = "ADXL345",
) -> dict[str, PlacedComponent]:
    """Generic SPI sensor breakout header.

    A 6-pin header (VCC, GND, SCK, MOSI, MISO, CS) for any SPI
    sensor module.

    Internal nets wired:
        - ``3V3`` on pin 1, ``GND`` on pin 2
        - ``SPI_SCK``, ``SPI_MOSI``, ``SPI_MISO``, ``SPI_CS``

    Returned keys: ``header``
    """
    x, y = pos

    header = pcb.place(
        _ref("J", ref_start), "Sensor_SPI_6pin", value=sensor_name,
        pos=(x, y), description=f"SPI sensor header ({sensor_name})",
    )

    pcb.power_net("3V3", [(header, "1")])
    pcb.power_net("GND", [(header, "2")])
    pcb.net("SPI_SCK", [(header, "3")])
    pcb.net("SPI_MOSI", [(header, "4")])
    pcb.net("SPI_MISO", [(header, "5")])
    pcb.net("SPI_CS", [(header, "6")])

    return {"header": header}


# ---------------------------------------------------------------------------
# 24. MOSFET Switch
# ---------------------------------------------------------------------------

def mosfet_switch(
    pcb: PCBDesign,
    ref_start: int,
    pos: tuple[float, float],
    gpio_net: str = "FET_CTRL",
) -> dict[str, PlacedComponent]:
    """N-channel MOSFET low-side switch with gate resistor.

    Drives a load (connected between LOAD+ and drain) from a GPIO pin
    via a SOT-23-3 N-FET.  Includes a gate pull-down resistor to
    keep the FET off when the GPIO is floating.

    Internal nets wired:
        - ``GND`` on source
        - ``gpio_net`` on gate resistor input

    Returned keys: ``mosfet``, ``r_gate``, ``r_pulldown``
    """
    x, y = pos

    mosfet = pcb.place(
        _ref("Q", ref_start), "SOT-23-3", value="2N7002",
        pos=(x, y), description="N-channel MOSFET switch",
    )
    r_gate = pcb.place(
        _ref("R", ref_start, 1), "R_0603", value="100",
        pos=(x - 4, y), description="Gate resistor",
    )
    r_pulldown = pcb.place(
        _ref("R", ref_start, 2), "R_0603", value="10k",
        pos=(x - 4, y + 3), description="Gate pull-down",
    )

    # Gate via resistor
    pcb.net(gpio_net, [(r_gate, "1")])
    pcb.net(f"{gpio_net}_GATE", [(r_gate, "2"), (mosfet, "1"), (r_pulldown, "1")])
    pcb.power_net("GND", [(mosfet, "2"), (r_pulldown, "2")])

    return {"mosfet": mosfet, "r_gate": r_gate, "r_pulldown": r_pulldown}


# ===========================================================================
# Subcircuit Registry
# ===========================================================================

# Return-key documentation: maps subcircuit name → list of dict keys
# returned by the function.  LLMs need this to wire subcircuits together.
SUBCIRCUIT_RETURN_KEYS: dict[str, list[str]] = {
    "usb_c_power": ["usb", "c_filter1", "c_filter2"],
    "usb_micro_power": ["usb", "c_filter"],
    "ldo_3v3": ["ldo", "c_in", "c_out"],
    "ldo_5v": ["ldo", "c_in", "c_out"],
    "buck_converter": ["ic", "inductor", "c_in", "c_out"],
    "esp32_minimal": ["esp32", "c_byp1", "c_byp2", "r_en", "r_io0",
                       "btn_reset", "btn_boot"],
    "stm32_minimal": ["mcu", "c_byp1", "c_byp2", "c_byp3", "r_reset",
                       "c_reset", "btn_reset"],
    "i2c_pullups": ["r_sda", "r_scl"],
    "uart_header": ["header"],
    "spi_header": ["header"],
    "debug_header": ["header"],
    "led_with_resistor": ["resistor", "led"],
    "button_with_pullup": ["btn", "resistor", "cap"],
    "voltage_divider": ["r_top", "r_bottom"],
    "decoupling_cap": ["cap"],
    "mounting_holes_corners": ["hole_tl", "hole_tr", "hole_br", "hole_bl"],
    "neopixel_strip": ["led_0", "led_1", "c_bulk"],
    "crystal_oscillator": ["crystal", "c_load1", "c_load2"],
    "h_bridge": ["q_ah", "q_al", "q_bh", "q_bl", "d_ah", "d_al",
                  "d_bh", "d_bl"],
    "barrel_jack_power": ["jack", "diode", "c_filter"],
    "relay_driver": ["relay", "transistor", "diode", "r_base"],
    "i2c_sensor_breakout": ["header", "r_sda", "r_scl"],
    "spi_sensor_breakout": ["header"],
    "mosfet_switch": ["mosfet", "r_gate", "r_pulldown"],
}


SUBCIRCUIT_REGISTRY: dict[str, tuple[callable, str, list[str]]] = {
    "usb_c_power": (
        usb_c_power,
        "USB Type-C connector with VBUS filter capacitors",
        ["VBUS", "GND"],
    ),
    "usb_micro_power": (
        usb_micro_power,
        "USB Micro-B connector with VBUS filter capacitor",
        ["VBUS", "GND"],
    ),
    "ldo_3v3": (
        ldo_3v3,
        "AMS1117-3.3 LDO regulator (SOT-223) with input/output caps",
        ["VBUS", "3V3", "GND"],
    ),
    "ldo_5v": (
        ldo_5v,
        "5V LDO regulator (SOT-223) with input/output caps",
        ["VIN", "5V", "GND"],
    ),
    "buck_converter": (
        buck_converter,
        "Generic buck converter placeholder (SOT-23-3 + inductor + caps)",
        ["VIN", "GND", "BUCK_SW", "BUCK_OUT"],
    ),
    "esp32_minimal": (
        esp32_minimal,
        "ESP32-WROOM-32 with bypass caps, EN/IO0 pull-ups, reset/boot buttons",
        ["3V3", "GND", "EN", "IO0"],
    ),
    "stm32_minimal": (
        stm32_minimal,
        "STM32 (QFP-48 placeholder) with bypass caps and reset circuit",
        ["3V3", "GND", "NRST"],
    ),
    "i2c_pullups": (
        i2c_pullups,
        "4.7k pull-up resistors for I2C SDA and SCL lines",
        ["3V3"],
    ),
    "uart_header": (
        uart_header,
        "1x04 pin header: VCC, GND, TX, RX",
        ["3V3", "GND"],
    ),
    "spi_header": (
        spi_header,
        "1x06 pin header: VCC, GND, MOSI, MISO, SCK, CS",
        ["3V3", "GND"],
    ),
    "debug_header": (
        debug_header,
        "1x06 debug header: 3V3, GND, TXD, RXD, IO0, EN",
        ["3V3", "GND"],
    ),
    "led_with_resistor": (
        led_with_resistor,
        "Single indicator LED with current-limiting resistor",
        ["GND"],
    ),
    "button_with_pullup": (
        button_with_pullup,
        "Pushbutton with 10k pull-up resistor and 100nF debounce cap",
        ["3V3", "GND"],
    ),
    "voltage_divider": (
        voltage_divider,
        "Two-resistor voltage divider (configurable values)",
        ["GND"],
    ),
    "decoupling_cap": (
        decoupling_cap,
        "Single decoupling capacitor (pin 2 = GND)",
        ["GND"],
    ),
    "mounting_holes_corners": (
        mounting_holes_corners,
        "4x M3 mounting holes at board corners (takes board_width, board_height)",
        [],
    ),
    "neopixel_strip": (
        neopixel_strip,
        "Horizontal WS2812B NeoPixel strip (configurable count and pitch)",
        ["VCC", "GND"],
    ),
    "crystal_oscillator": (
        crystal_oscillator,
        "Crystal oscillator (R_0603 placeholder) with two load capacitors",
        ["GND", "XTAL_IN", "XTAL_OUT"],
    ),
    "h_bridge": (
        h_bridge,
        "Full H-bridge with 4x SOT-23-3 MOSFETs and flyback diodes",
        ["VCC", "GND", "MOTOR_A", "MOTOR_B"],
    ),
    "barrel_jack_power": (
        barrel_jack_power,
        "Barrel jack with polarity protection diode and input filter cap",
        ["VIN", "GND", "JACK_TIP"],
    ),
    "relay_driver": (
        relay_driver,
        "SPDT relay with NPN transistor driver and flyback diode",
        ["VBUS", "GND"],
    ),
    "i2c_sensor_breakout": (
        i2c_sensor_breakout,
        "I2C sensor header (4-pin) with optional pull-ups (BME280, SHT31, etc.)",
        ["3V3", "GND", "I2C_SDA", "I2C_SCL"],
    ),
    "spi_sensor_breakout": (
        spi_sensor_breakout,
        "SPI sensor header (6-pin) for ADXL345, BME280-SPI, etc.",
        ["3V3", "GND", "SPI_SCK", "SPI_MOSI", "SPI_MISO", "SPI_CS"],
    ),
    "mosfet_switch": (
        mosfet_switch,
        "N-channel MOSFET low-side switch with gate resistor and pull-down",
        ["GND"],
    ),
}


# ===========================================================================
# Discovery / Documentation Helpers
# ===========================================================================

def list_subcircuits() -> str:
    """Return a formatted multi-line string listing all available subcircuits.

    Each entry shows the function name, a one-line description, the
    internal power/signal nets wired automatically, and — critically —
    the dict keys returned so the caller knows how to reference the
    placed components.
    """
    lines = ["Available subcircuit building blocks:", ""]

    for name, (func, description, nets) in sorted(SUBCIRCUIT_REGISTRY.items()):
        nets_str = ", ".join(nets) if nets else "(none)"
        keys = SUBCIRCUIT_RETURN_KEYS.get(name, [])
        keys_str = ", ".join(keys) if keys else "(none)"
        lines.append(f"  {name}")
        lines.append(f"    {description}")
        lines.append(f"    Internal nets: {nets_str}")
        lines.append(f"    Returns dict keys: {keys_str}")
        lines.append("")

    return "\n".join(lines)


def describe_subcircuit(name: str) -> str:
    """Return detailed usage information for a single subcircuit.

    Includes the function signature, full docstring, internal nets,
    and the dict keys returned.

    Args:
        name: Subcircuit name as it appears in ``SUBCIRCUIT_REGISTRY``.

    Returns:
        A multi-line string with full documentation, or an error
        message if the name is not found.
    """
    entry = SUBCIRCUIT_REGISTRY.get(name)
    if entry is None:
        available = ", ".join(sorted(SUBCIRCUIT_REGISTRY.keys()))
        return (
            f"Unknown subcircuit '{name}'.\n"
            f"Available subcircuits: {available}"
        )

    func, description, nets = entry

    # Build signature info
    import inspect
    sig = inspect.signature(func)
    params = []
    for pname, param in sig.parameters.items():
        if param.default is inspect.Parameter.empty:
            params.append(pname)
        else:
            params.append(f"{pname}={param.default!r}")
    sig_str = f"{name}({', '.join(params)})"

    # Extract docstring
    docstring = inspect.getdoc(func) or "(no docstring)"

    nets_str = ", ".join(nets) if nets else "(none)"

    lines = [
        f"Subcircuit: {name}",
        f"{'=' * (len('Subcircuit: ') + len(name))}",
        "",
        f"Signature: {sig_str}",
        "",
        f"Description: {description}",
        "",
        f"Internal nets (auto-wired): {nets_str}",
        "",
        "Documentation:",
        "-" * 40,
        docstring,
    ]

    return "\n".join(lines)
