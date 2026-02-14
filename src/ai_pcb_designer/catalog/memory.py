"""Memory ICs: DDR, Flash, EEPROM, SRAM."""

MEMORY = [
    # ── DDR3/DDR3L SDRAM ───────────────────────────────────────────────
    {"mpn": "MT41K256M16HA-125:E", "description": "DDR3L 4Gbit x16 1.35V TSOP-54",
     "package": "TSOP-54", "pins": 54, "category": "ddr3",
     "key_specs": {"density": "4Gbit", "width": "x16", "voltage": 1.35,
                   "speed": "1600MT/s", "use": "ARM application processor main memory"}},
    {"mpn": "AS4C256M16D3A-12BIN", "description": "DDR3 4Gbit x16 1.5V TSOP-54",
     "package": "TSOP-54", "pins": 54, "category": "ddr3",
     "key_specs": {"density": "4Gbit", "width": "x16", "voltage": 1.5,
                   "speed": "1600MT/s"}},
    {"mpn": "K4B4G1646E-BYMA", "description": "DDR3L 4Gbit x16 Samsung TSOP-54",
     "package": "TSOP-54", "pins": 54, "category": "ddr3",
     "key_specs": {"density": "4Gbit", "width": "x16", "voltage": 1.35,
                   "speed": "1600MT/s"}},
    {"mpn": "MT41K128M16JT-125", "description": "DDR3L 2Gbit x16 TSOP-54",
     "package": "TSOP-54", "pins": 54, "category": "ddr3",
     "key_specs": {"density": "2Gbit", "width": "x16", "voltage": 1.35}},

    # ── SPI NOR Flash ──────────────────────────────────────────────────
    {"mpn": "W25Q128JVSIQ", "description": "128Mbit SPI flash SOIC-8",
     "package": "SOIC-8", "pins": 8, "category": "spi_flash",
     "key_specs": {"density": "128Mbit", "interface": "SPI/QSPI",
                   "freq_mhz": 133, "voltage": "2.7-3.6V",
                   "pinout": "1=CS 2=DO 3=WP 4=GND 5=DI 6=CLK 7=HOLD 8=VCC"}},
    {"mpn": "W25Q32JVSSIQ", "description": "32Mbit SPI flash SOIC-8",
     "package": "SOIC-8", "pins": 8, "category": "spi_flash",
     "key_specs": {"density": "32Mbit", "interface": "SPI/QSPI",
                   "freq_mhz": 133, "voltage": "2.7-3.6V"}},
    {"mpn": "S25FL128LAGMFI010", "description": "128Mbit SPI flash SOIC-16 wide",
     "package": "SOIC-16", "pins": 16, "category": "spi_flash",
     "key_specs": {"density": "128Mbit", "interface": "SPI/QSPI",
                   "freq_mhz": 133}},
    {"mpn": "S25FL127SAGMFI011", "description": "128Mbit SPI flash WSON-8",
     "package": "WSON-8", "pins": 8, "category": "spi_flash",
     "key_specs": {"density": "128Mbit", "interface": "SPI",
                   "voltage": "1.7-3.6V"}},

    # ── eMMC ───────────────────────────────────────────────────────────
    {"mpn": "THGBMJG6C1LBAIL", "description": "8GB eMMC 5.1 BGA-153",
     "package": "BGA-100", "pins": 100, "category": "emmc",
     "key_specs": {"density": "8GB", "interface": "eMMC 5.1",
                   "use": "embedded storage for Linux SoC"}},

    # ── EEPROM ─────────────────────────────────────────────────────────
    {"mpn": "AT24C256C-SSHL-T", "description": "256Kbit I2C EEPROM SOIC-8",
     "package": "SOIC-8", "pins": 8, "category": "eeprom",
     "key_specs": {"density": "256Kbit", "interface": "I2C", "voltage": "1.7-5.5V",
                   "pinout": "1=A0 2=A1 3=A2 4=GND 5=SDA 6=SCL 7=WP 8=VCC"}},
    {"mpn": "24LC64-I/SN", "description": "64Kbit I2C EEPROM SOIC-8",
     "package": "SOIC-8", "pins": 8, "category": "eeprom",
     "key_specs": {"density": "64Kbit", "interface": "I2C"}},

    # ── SRAM (for FPGA, special use) ───────────────────────────────────
    {"mpn": "IS62WV12816BLL-55TLI", "description": "2Mbit parallel SRAM TSOP-44",
     "package": "TSOP-54", "pins": 44, "category": "sram",
     "key_specs": {"density": "2Mbit", "width": "x16", "access_ns": 55}},
]
