"""Minimal AS5600 bench test for Raspberry Pi Pico 2 W.

Wiring:
    AS5600 VCC -> Pico 3V3(OUT)
    AS5600 GND -> Pico GND
    AS5600 SDA -> Pico GP4
    AS5600 SCL -> Pico GP5

This test intentionally has no Wi-Fi, web server, filtering, calibration,
or Mills selection logic. Upload it as ``main.py`` for the bench test, or
run it from the REPL with ``exec(open(...).read())``.
"""

from machine import I2C, Pin
import time


AS5600_ADDRESS = 0x36
RAW_ANGLE_REGISTER = 0x0C
STATUS_REGISTER = 0x0B
AGC_REGISTER = 0x1A
MAGNITUDE_REGISTER = 0x1B

SDA_PIN = 4
SCL_PIN = 5
SAMPLE_DELAY_MS = 200  # 5 readings per second


def read_u16(register):
    """Read a big-endian 16-bit AS5600 register pair."""
    data = i2c.readfrom_mem(AS5600_ADDRESS, register, 2)
    return (data[0] << 8) | data[1]


def status_text(status):
    magnet_detected = bool(status & 0x20)  # MD
    magnet_weak = bool(status & 0x10)      # ML
    magnet_strong = bool(status & 0x08)    # MH
    return "detected={}, weak={}, strong={}".format(
        "YES" if magnet_detected else "NO",
        "YES" if magnet_weak else "NO",
        "YES" if magnet_strong else "NO",
    )


def scan_bus():
    devices = i2c.scan()
    formatted = ["0x{:02X}".format(address) for address in devices]
    print("I2C devices:", ", ".join(formatted) if formatted else "none")
    return AS5600_ADDRESS in devices


i2c = I2C(0, sda=Pin(SDA_PIN), scl=Pin(SCL_PIN), freq=100000)

print("\nAS5600 bench test")
print("I2C: SDA=GP{}, SCL=GP{}".format(SDA_PIN, SCL_PIN))
print("Expected AS5600 address: 0x{:02X}".format(AS5600_ADDRESS))

if not scan_bus():
    print("AS5600 not detected. Check power, ground, SDA, and SCL.")
    print("The test will retry the bus scan every 2 seconds.")

last_scan_ms = time.ticks_ms()
sensor_present = AS5600_ADDRESS in i2c.scan()

while True:
    now = time.ticks_ms()

    if not sensor_present:
        if time.ticks_diff(now, last_scan_ms) >= 2000:
            last_scan_ms = now
            sensor_present = scan_bus()
        time.sleep_ms(SAMPLE_DELAY_MS)
        continue

    try:
        raw_angle = read_u16(RAW_ANGLE_REGISTER) & 0x0FFF
        angle_degrees = raw_angle * 360.0 / 4096.0
        status = i2c.readfrom_mem(AS5600_ADDRESS, STATUS_REGISTER, 1)[0]
        agc = i2c.readfrom_mem(AS5600_ADDRESS, AGC_REGISTER, 1)[0]
        magnitude = read_u16(MAGNITUDE_REGISTER)

        print(
            "raw={:4d}  angle={:7.2f} deg  status=0x{:02X} ({})  "
            "AGC={:3d}  magnitude={:4d}".format(
                raw_angle,
                angle_degrees,
                status,
                status_text(status),
                agc,
                magnitude,
            )
        )
    except OSError as error:
        print("AS5600 read error:", error)
        sensor_present = False

    time.sleep_ms(SAMPLE_DELAY_MS)
