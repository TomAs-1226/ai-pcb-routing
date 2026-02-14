"""Sensors: temperature, pressure, IMU, current, light, etc."""

SENSORS = [
    # ── Environmental ──────────────────────────────────────────────────
    {"mpn": "BME280", "description": "Temp/humidity/pressure I2C/SPI QFN-8",
     "package": "QFN-8", "pins": 8, "category": "environmental",
     "key_specs": {"interface": "I2C/SPI", "vdd": "1.71-3.6V",
                   "measures": "temperature, humidity, pressure",
                   "i2c_addr": "0x76/0x77"}},
    {"mpn": "BMP280", "description": "Temp/pressure I2C/SPI QFN-8",
     "package": "QFN-8", "pins": 8, "category": "environmental",
     "key_specs": {"interface": "I2C/SPI", "vdd": "1.71-3.6V",
                   "measures": "temperature, pressure"}},
    {"mpn": "SHT30-DIS-B2.5KS", "description": "Temp/humidity I2C DFN-8",
     "package": "DFN-8", "pins": 8, "category": "environmental",
     "key_specs": {"interface": "I2C", "vdd": "2.15-5.5V",
                   "accuracy": "±0.2°C, ±2%RH"}},
    {"mpn": "HDC1080DMBR", "description": "Temp/humidity I2C WSON-6",
     "package": "DFN-8", "pins": 6, "category": "environmental",
     "key_specs": {"interface": "I2C", "vdd": "2.7-5.5V"}},

    # ── IMU / Motion ───────────────────────────────────────────────────
    {"mpn": "MPU-6050", "description": "6-axis accel+gyro I2C QFN-24",
     "package": "QFN-24", "pins": 24, "category": "imu",
     "key_specs": {"interface": "I2C", "axes": 6, "vdd": "2.375-3.46V",
                   "i2c_addr": "0x68/0x69"}},
    {"mpn": "ICM-42688-P", "description": "6-axis high-perf IMU SPI/I2C QFN-14",
     "package": "QFN-16", "pins": 14, "category": "imu",
     "key_specs": {"interface": "SPI/I2C", "axes": 6, "vdd": "1.71-3.6V",
                   "accel_range": "±16g", "gyro_range": "±2000dps"}},
    {"mpn": "ADXL345BCCZ-RL", "description": "3-axis accelerometer SPI/I2C QFN-14",
     "package": "QFN-16", "pins": 14, "category": "accelerometer",
     "key_specs": {"interface": "SPI/I2C", "axes": 3, "range": "±16g"}},

    # ── Current / Power ────────────────────────────────────────────────
    {"mpn": "INA219AIDR", "description": "Bidirectional current/power monitor I2C SOIC-8",
     "package": "SOIC-8", "pins": 8, "category": "current_sensor",
     "key_specs": {"interface": "I2C", "vbus_max": 26, "resolution_bits": 12,
                   "i2c_addr": "0x40-0x4F (configurable)"}},
    {"mpn": "INA226AIDGSR", "description": "High-precision current/power monitor I2C TSSOP-10",
     "package": "TSSOP-10", "pins": 10, "category": "current_sensor",
     "key_specs": {"interface": "I2C", "vbus_max": 36, "resolution_bits": 16}},
    {"mpn": "ACS712ELCTR-05B-T", "description": "5A Hall current sensor SOIC-8",
     "package": "SOIC-8", "pins": 8, "category": "current_sensor",
     "key_specs": {"range_a": 5, "sensitivity_mv_a": 185,
                   "output": "analog voltage"}},

    # ── ADC ────────────────────────────────────────────────────────────
    {"mpn": "ADS1115IDGSR", "description": "16-bit 4-ch ADC I2C TSSOP-10",
     "package": "TSSOP-10", "pins": 10, "category": "adc",
     "key_specs": {"resolution_bits": 16, "channels": 4, "interface": "I2C",
                   "rate_sps": 860, "vdd": "2.0-5.5V"}},
    {"mpn": "MCP3008-I/SL", "description": "10-bit 8-ch ADC SPI SOIC-16",
     "package": "SOIC-16", "pins": 16, "category": "adc",
     "key_specs": {"resolution_bits": 10, "channels": 8, "interface": "SPI",
                   "rate_ksps": 200}},

    # ── Temperature (thermocouple) ─────────────────────────────────────
    {"mpn": "MAX6675ISA+T", "description": "K-thermocouple-to-digital SPI SOIC-8",
     "package": "SOIC-8", "pins": 8, "category": "thermocouple",
     "key_specs": {"interface": "SPI", "resolution": "0.25°C",
                   "range": "0-1024°C"}},
    {"mpn": "MAX31855KASA+T", "description": "K-thermocouple-to-digital SPI SOIC-8",
     "package": "SOIC-8", "pins": 8, "category": "thermocouple",
     "key_specs": {"interface": "SPI", "resolution": "0.25°C",
                   "range": "-200 to 1350°C"}},

    # ── Load Cell ──────────────────────────────────────────────────────
    {"mpn": "HX711", "description": "24-bit ADC for load cells SOIC-16",
     "package": "SOIC-16", "pins": 16, "category": "load_cell_adc",
     "key_specs": {"resolution_bits": 24, "channels": 2, "gain": "128/64",
                   "interface": "serial (DOUT/SCK)"}},

    # ── Light ──────────────────────────────────────────────────────────
    {"mpn": "BH1750FVI-TR", "description": "Ambient light sensor I2C SOIC-8",
     "package": "SOIC-8", "pins": 8, "category": "light",
     "key_specs": {"interface": "I2C", "range_lux": "1-65535",
                   "resolution_lux": 1}},
    {"mpn": "TSL2591", "description": "High dynamic range light sensor DFN-6",
     "package": "DFN-8", "pins": 6, "category": "light",
     "key_specs": {"interface": "I2C", "dynamic_range": "600M:1"}},

    # ── Display Drivers ────────────────────────────────────────────────
    {"mpn": "SSD1306", "description": "128x64 OLED driver I2C/SPI",
     "package": "OLED_SSD1306", "pins": 4, "category": "display_driver",
     "key_specs": {"interface": "I2C/SPI", "resolution": "128x64",
                   "i2c_pinout": "1=GND 2=VCC 3=SCL 4=SDA"}},
]
