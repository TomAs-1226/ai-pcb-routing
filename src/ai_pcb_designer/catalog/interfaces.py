"""Interface ICs: USB, Ethernet PHY, CAN, RS-485, level shifters, etc."""

INTERFACES = [
    # ── USB-to-UART bridges ────────────────────────────────────────────
    {"mpn": "CH340G", "description": "USB-UART bridge SOIC-16",
     "package": "SOIC-16", "pins": 16, "category": "usb_uart",
     "key_specs": {"baud_max": 2000000, "vdd": "3.3/5V",
                   "pinout": "needs 12MHz crystal"}},
    {"mpn": "CP2102N-A02-GQFN24", "description": "USB-UART bridge QFN-24",
     "package": "QFN-24", "pins": 24, "category": "usb_uart",
     "key_specs": {"baud_max": 3000000, "vdd": "3.0-3.6V",
                   "no_crystal": True}},
    {"mpn": "FT232RL", "description": "USB-UART bridge SSOP-28",
     "package": "SOIC-28", "pins": 28, "category": "usb_uart",
     "key_specs": {"baud_max": 3000000, "vdd": "3.3/5V"}},

    # ── USB PD Controllers ─────────────────────────────────────────────
    {"mpn": "STUSB4500QTR", "description": "USB PD sink controller QFN-24",
     "package": "QFN-24", "pins": 24, "category": "usb_pd",
     "key_specs": {"pd_rev": "3.0", "role": "sink", "vdd": "3.0-5.5V",
                   "max_voltage": 20, "max_current_a": 5,
                   "i2c_config": True}},
    {"mpn": "FUSB302BMPX", "description": "USB Type-C PD PHY QFN-16",
     "package": "QFN-16", "pins": 16, "category": "usb_pd",
     "key_specs": {"pd_rev": "2.0", "role": "DRP/source/sink",
                   "i2c_control": True}},
    {"mpn": "CYPD3177-24LQXQ", "description": "USB PD sink controller QFN-24",
     "package": "QFN-24", "pins": 24, "category": "usb_pd",
     "key_specs": {"pd_rev": "3.0", "role": "sink", "max_voltage": 20,
                   "config": "resistor-programmable"}},

    # ── Ethernet PHY ───────────────────────────────────────────────────
    {"mpn": "LAN8720A-CP-TR", "description": "10/100 Ethernet PHY RMII QFN-24",
     "package": "QFN-24", "pins": 24, "category": "ethernet_phy",
     "key_specs": {"speed": "10/100Mbps", "interface": "RMII",
                   "vdd": "3.3V", "needs": "25MHz crystal + RJ45 magnetics"}},
    {"mpn": "KSZ8081RNA", "description": "10/100 Ethernet PHY RMII QFN-24",
     "package": "QFN-24", "pins": 24, "category": "ethernet_phy",
     "key_specs": {"speed": "10/100Mbps", "interface": "RMII/MII",
                   "vdd": "3.3V"}},
    {"mpn": "DP83848CVV/NOPB", "description": "10/100 Ethernet PHY MII LQFP-48",
     "package": "LQFP-48", "pins": 48, "category": "ethernet_phy",
     "key_specs": {"speed": "10/100Mbps", "interface": "MII/RMII",
                   "vdd": "3.3V"}},
    {"mpn": "RTL8211FDI-CG", "description": "10/100/1000 Gigabit PHY QFN-48",
     "package": "QFN-48", "pins": 48, "category": "ethernet_phy",
     "key_specs": {"speed": "10/100/1000Mbps", "interface": "RGMII",
                   "vdd": "3.3V"}},

    # ── CAN Transceivers ───────────────────────────────────────────────
    {"mpn": "SN65HVD230DR", "description": "CAN transceiver 3.3V SOIC-8",
     "package": "SOIC-8", "pins": 8, "category": "can",
     "key_specs": {"speed": "1Mbps", "vdd": "3.3V",
                   "pinout": "1=TXD 2=GND 3=VCC 4=RXD 5=VREF 6=CANL 7=CANH 8=RS"}},
    {"mpn": "MCP2551-I/SN", "description": "CAN transceiver 5V SOIC-8",
     "package": "SOIC-8", "pins": 8, "category": "can",
     "key_specs": {"speed": "1Mbps", "vdd": "5V"}},

    # ── RS-485 Transceivers ────────────────────────────────────────────
    {"mpn": "MAX485ESA+T", "description": "RS-485 half-duplex SOIC-8",
     "package": "SOIC-8", "pins": 8, "category": "rs485",
     "key_specs": {"speed": "2.5Mbps", "vdd": "5V", "half_duplex": True}},
    {"mpn": "SN65HVD72DR", "description": "RS-485 full-duplex SOIC-8",
     "package": "SOIC-8", "pins": 8, "category": "rs485",
     "key_specs": {"speed": "50Mbps", "vdd": "3.3V", "full_duplex": True}},

    # ── Level Shifters ─────────────────────────────────────────────────
    {"mpn": "TXS0108EPWR", "description": "8-bit bidirectional level shifter TSSOP-20",
     "package": "TSSOP-20", "pins": 20, "category": "level_shifter",
     "key_specs": {"channels": 8, "va": "1.2-3.6V", "vb": "1.65-5.5V",
                   "bidirectional": True}},
    {"mpn": "BSS138", "description": "N-FET for discrete level shifting SOT-23",
     "package": "SOT-23", "pins": 3, "category": "level_shifter",
     "key_specs": {"type": "N-CH MOSFET", "vds": 50, "ids_ma": 220,
                   "use": "1-channel I2C level shift with 2x pull-ups"}},
]
