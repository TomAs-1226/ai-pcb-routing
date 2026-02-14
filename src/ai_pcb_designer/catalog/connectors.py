"""Connectors: USB, headers, card slots, barrel jacks, RF, etc."""

CONNECTORS = [
    # ── USB ────────────────────────────────────────────────────────────
    {"mpn": "USB4125-GF-A-0190", "description": "USB Type-C 16-pin SMT receptacle",
     "package": "USB_C_16pin", "pins": 16, "category": "usb_c",
     "key_specs": {"type": "USB-C", "current_a": 3.0,
                   "pinout": "A1=GND A4=VBUS A6=D+ A7=D- B1=GND B4=VBUS"}},
    {"mpn": "10118194-0001LF", "description": "USB Micro-B SMT receptacle",
     "package": "USB_Micro_B", "pins": 5, "category": "usb_micro",
     "key_specs": {"type": "Micro-B", "pinout": "1=VBUS 2=D- 3=D+ 4=ID 5=GND"}},
    {"mpn": "SS-52100-001", "description": "USB Type-A through-hole receptacle",
     "package": "PinHeader_1x04", "pins": 4, "category": "usb_a",
     "key_specs": {"type": "USB-A", "pinout": "1=VBUS 2=D- 3=D+ 4=GND"}},

    # ── Pin Headers ────────────────────────────────────────────────────
    {"mpn": "PinHeader-1x04-2.54mm", "description": "1x04 pin header 2.54mm",
     "package": "PinHeader_1x04", "pins": 4, "category": "header",
     "key_specs": {"pitch_mm": 2.54, "rows": 1, "cols": 4}},
    {"mpn": "PinHeader-1x06-2.54mm", "description": "1x06 pin header 2.54mm",
     "package": "PinHeader_1x06", "pins": 6, "category": "header",
     "key_specs": {"pitch_mm": 2.54, "rows": 1, "cols": 6}},
    {"mpn": "PinHeader-2x05-2.54mm", "description": "2x05 pin header for SWD/JTAG",
     "package": "PinHeader_2x05", "pins": 10, "category": "header",
     "key_specs": {"pitch_mm": 2.54, "use": "ARM SWD debug"}},
    {"mpn": "PinHeader-2x10-1.27mm", "description": "2x10 pin header 1.27mm JTAG",
     "package": "PinHeader_2x10", "pins": 20, "category": "header",
     "key_specs": {"pitch_mm": 1.27, "use": "20-pin JTAG/SWD"}},
    {"mpn": "PinHeader-2x20-2.54mm", "description": "2x20 pin header (Raspberry Pi style)",
     "package": "PinHeader_2x20", "pins": 40, "category": "header",
     "key_specs": {"pitch_mm": 2.54, "use": "GPIO expansion"}},

    # ── Card Slots ─────────────────────────────────────────────────────
    {"mpn": "DM3AT-SF-PEJM5", "description": "MicroSD card push-push SMT",
     "package": "MicroSD_Socket", "pins": 9, "category": "card_slot",
     "key_specs": {"type": "microSD", "interface": "SPI/SDIO",
                   "pinout": "1=CS 2=MOSI 3=VSS 4=VDD 5=CLK 6=VSS 7=DO"}},

    # ── Power Connectors ───────────────────────────────────────────────
    {"mpn": "PJ-002A", "description": "2.1mm barrel jack through-hole",
     "package": "BarrelJack_DC", "pins": 3, "category": "barrel_jack",
     "key_specs": {"barrel_mm": 2.1, "pinout": "1=Tip 2=Sleeve 3=Switch",
                   "voltage_max": 24, "current_max_a": 5}},
    {"mpn": "ScrewTerminal-2P-5.08mm", "description": "2-pos screw terminal 5.08mm",
     "package": "ScrewTerminal_2P", "pins": 2, "category": "screw_terminal",
     "key_specs": {"pitch_mm": 5.08, "current_max_a": 10}},
    {"mpn": "ScrewTerminal-3P-5.08mm", "description": "3-pos screw terminal 5.08mm",
     "package": "ScrewTerminal_3P", "pins": 3, "category": "screw_terminal",
     "key_specs": {"pitch_mm": 5.08, "current_max_a": 10}},

    # ── FPC / FFC ──────────────────────────────────────────────────────
    {"mpn": "FH12-24S-0.5SH(55)", "description": "24-pin FPC 0.5mm for camera",
     "package": "FPC_24pin", "pins": 24, "category": "fpc",
     "key_specs": {"pitch_mm": 0.5, "use": "camera (OV2640/OV5640)"}},
    {"mpn": "FH12-40S-0.5SH", "description": "40-pin FPC 0.5mm for LCD/TFT",
     "package": "FPC_40pin", "pins": 40, "category": "fpc",
     "key_specs": {"pitch_mm": 0.5, "use": "TFT LCD display"}},

    # ── Ethernet ───────────────────────────────────────────────────────
    {"mpn": "HR911105A", "description": "RJ45 MagJack 10/100 with LEDs",
     "package": "PinHeader_1x12", "pins": 12, "category": "ethernet_jack",
     "key_specs": {"type": "10/100 Ethernet", "magnetics": "integrated",
                   "leds": 2}},

    # ── Switches ───────────────────────────────────────────────────────
    {"mpn": "SKHHAJA010", "description": "6x6x3.5mm tactile switch SMT",
     "package": "SW_Push_6mm", "pins": 4, "category": "tactile_switch",
     "key_specs": {"force_gf": 160, "travel_mm": 0.25,
                   "pinout": "1-2=side_A 3-4=side_B"}},
    {"mpn": "TS-1187A-B-A-B", "description": "3x6mm tactile switch SMD",
     "package": "SW_Push_SMD", "pins": 2, "category": "tactile_switch",
     "key_specs": {"force_gf": 180, "size": "3x6mm"}},
]
