"""Preliminary Mills activity webhook receiver for Pico 2 W.

The Shelly reports that the Mills record stack is moving by calling:

    GET or POST /integrations/mills/stack-moving

This version records the event and samples the AS5600 for diagnostic use.
It does not yet contain calibration tables or selection reporting.
Copy secrets.example.py to secrets.py and fill in the Wi-Fi settings.
"""

import gc
import machine
import os
import socket
import time

import network
from machine import I2C, Pin
from secrets import WIFI_SSID, WIFI_PASSWORD

try:
    from secrets import OTA_TOKEN
except ImportError:
    OTA_TOKEN = ""


WEB_PORT = 80
WIFI_RETRY_MS = 10000
STACK_MOVING_PATH = "/integrations/mills/stack-moving"
IDLE_PATH = "/integrations/mills/idle"
OTA_PATH = "/ota"
OTA_TEMP_FILE = "main.new.py"
OTA_BACKUP_FILE = "main.backup.py"
OTA_MAX_BYTES = 64 * 1024
AS5600_ADDRESS = 0x36
RAW_ANGLE_REGISTER = 0x0C
STATUS_REGISTER = 0x0B
AGC_REGISTER = 0x1A
MAGNITUDE_REGISTER = 0x1B
AS5600_SAMPLE_MS = 100
MOVEMENT_THRESHOLD_RAW = 2
MOVEMENT_HOLD_MS = 250

wifi = None
mills_active = False
last_stack_event_ms = None
stack_event_count = 0
last_event_method = None
last_event_path = None
last_event_error = None
sensor_present = False
raw_angle = None
angle_degrees = None
sensor_status = None
agc_value = None
magnitude_value = None
previous_raw_angle = None
last_angle_change_ms = None
wheel_moving = False
wheel_moved_while_active = False
stable_since_ms = None
ota_reboot_pending = False
last_ota_status = "not used"

i2c = I2C(0, sda=Pin(4), scl=Pin(5), freq=100000)


def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if wlan.isconnected():
        return wlan

    print("Connecting to Wi-Fi...")
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    deadline = time.ticks_add(time.ticks_ms(), 20000)
    while not wlan.isconnected() and time.ticks_diff(deadline, time.ticks_ms()) > 0:
        time.sleep_ms(250)

    if wlan.isconnected():
        print("Wi-Fi connected:", wlan.ifconfig())
    else:
        print("Wi-Fi connection failed")
    return wlan


def http_response(client, status, body, content_type="application/json"):
    payload = body.encode()
    header = (
        "HTTP/1.1 {}\r\n"
        "Content-Type: {}; charset=utf-8\r\n"
        "Content-Length: {}\r\n"
        "Cache-Control: no-store\r\n"
        "Connection: close\r\n\r\n"
    ).format(status, content_type, len(payload))
    client.send(header.encode())
    client.send(payload)


def safe_remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def read_request(client):
    """Read request headers and return method, path, headers, initial body."""
    data = b""
    while b"\r\n\r\n" not in data and len(data) <= 4096:
        chunk = client.recv(512)
        if not chunk:
            break
        data += chunk

    marker = data.find(b"\r\n\r\n")
    if marker < 0 or marker > 4096:
        raise ValueError("incomplete or oversized HTTP headers")

    header_bytes = data[:marker]
    initial_body = data[marker + 4:]
    lines = header_bytes.split(b"\r\n")
    request_parts = lines[0].decode().split()
    if len(request_parts) != 3:
        raise ValueError("malformed request line")

    headers = {}
    for line in lines[1:]:
        if b":" not in line:
            raise ValueError("malformed HTTP header")
        name, value = line.split(b":", 1)
        headers[name.decode().lower().strip()] = value.decode().strip()

    try:
        content_length = int(headers.get("content-length", "0"))
    except ValueError:
        raise ValueError("invalid Content-Length")
    if content_length < 0 or content_length > OTA_MAX_BYTES:
        raise ValueError("upload exceeds {} bytes".format(OTA_MAX_BYTES))

    return request_parts[0], request_parts[1], headers, initial_body, content_length


def receive_ota_file(client, initial_body, content_length):
    """Receive a complete upload into the temporary file."""
    if len(initial_body) > content_length:
        raise ValueError("request body exceeds Content-Length")

    received = 0
    with open(OTA_TEMP_FILE, "wb") as upload:
        if initial_body:
            upload.write(initial_body)
            received = len(initial_body)
        while received < content_length:
            chunk = client.recv(min(1024, content_length - received))
            if not chunk:
                raise ValueError("upload ended early ({}/{})".format(received, content_length))
            upload.write(chunk)
            received += len(chunk)
        upload.flush()

    if received != content_length:
        raise ValueError("incomplete upload ({}/{})".format(received, content_length))


def install_ota_file():
    """Validate and install the complete staged file, retaining a backup."""
    # compile() checks syntax without executing the uploaded program.
    with open(OTA_TEMP_FILE, "rb") as upload:
        source = upload.read()
    compile(source, OTA_TEMP_FILE, "exec")

    safe_remove(OTA_BACKUP_FILE)
    os.rename("main.py", OTA_BACKUP_FILE)
    try:
        os.rename(OTA_TEMP_FILE, "main.py")
    except Exception:
        # Restore the known working program if the second rename fails.
        os.rename(OTA_BACKUP_FILE, "main.py")
        raise


def read_u16(register):
    data = i2c.readfrom_mem(AS5600_ADDRESS, register, 2)
    return (data[0] << 8) | data[1]


def update_sensor():
    global sensor_present, raw_angle, angle_degrees, sensor_status
    global agc_value, magnitude_value, previous_raw_angle
    global last_angle_change_ms, wheel_moving, wheel_moved_while_active
    global stable_since_ms

    now = time.ticks_ms()
    try:
        if not sensor_present:
            if AS5600_ADDRESS not in i2c.scan():
                return
            sensor_present = True

        current_raw = read_u16(RAW_ANGLE_REGISTER) & 0x0FFF
        sensor_status = i2c.readfrom_mem(AS5600_ADDRESS, STATUS_REGISTER, 1)[0]
        agc_value = i2c.readfrom_mem(AS5600_ADDRESS, AGC_REGISTER, 1)[0]
        magnitude_value = read_u16(MAGNITUDE_REGISTER)
        raw_angle = current_raw
        angle_degrees = current_raw * 360.0 / 4096.0

        changed = False
        if previous_raw_angle is not None:
            # Use the shortest signed path so 4095 -> 0 is small movement.
            delta = (current_raw - previous_raw_angle + 2048) % 4096 - 2048
            changed = abs(delta) >= MOVEMENT_THRESHOLD_RAW
        previous_raw_angle = current_raw

        if changed:
            last_angle_change_ms = now
            stable_since_ms = None
            if mills_active:
                wheel_moved_while_active = True
        elif stable_since_ms is None:
            stable_since_ms = now

        wheel_moving = (
            last_angle_change_ms is not None
            and time.ticks_diff(now, last_angle_change_ms) < MOVEMENT_HOLD_MS
        )
    except OSError as error:
        sensor_present = False
        wheel_moving = False
        print("AS5600 read error:", error)


def sensor_status_text():
    if sensor_status is None:
        return "unknown"
    return "detected={}, weak={}, strong={}".format(
        "YES" if sensor_status & 0x20 else "NO",
        "YES" if sensor_status & 0x10 else "NO",
        "YES" if sensor_status & 0x08 else "NO",
    )


def status_json():
    ip = wifi.ifconfig()[0] if wifi and wifi.isconnected() else None
    return (
        '{{"mills_active":{},"last_stack_event_ms":{},'
        '"stack_event_count":{},"ip":{},"sensor_present":{},'
        '"raw_angle":{},"angle_degrees":{},"wheel_moving":{},'
        '"wheel_moved_while_active":{},"stable_ms":{},'
        '"sensor_status":"{}","agc":{},"magnitude":{},'
        '"ota_status":"{}"}}'
    ).format(
        "true" if mills_active else "false",
        "null" if last_stack_event_ms is None else last_stack_event_ms,
        stack_event_count,
        "null" if ip is None else '"{}"'.format(ip),
        "true" if sensor_present else "false",
        "null" if raw_angle is None else raw_angle,
        "null" if angle_degrees is None else "{:.2f}".format(angle_degrees),
        "true" if wheel_moving else "false",
        "true" if wheel_moved_while_active else "false",
        "null" if stable_since_ms is None else time.ticks_diff(time.ticks_ms(), stable_since_ms),
        sensor_status_text(),
        "null" if agc_value is None else agc_value,
        "null" if magnitude_value is None else magnitude_value,
        last_ota_status,
    )


def status_html():
    ip = wifi.ifconfig()[0] if wifi and wifi.isconnected() else "offline"
    last_event = "never" if last_stack_event_ms is None else "{} ms ago".format(
        time.ticks_diff(time.ticks_ms(), last_stack_event_ms)
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>Mills Pico</title></head><body>"
        "<h1>Mills Pico webhook receiver</h1>"
        "<p><b>IP:</b> {}</p>"
        "<p><b>Mills active:</b> {}</p>"
        "<p><b>Last stack-moving event:</b> {}</p>"
        "<p><b>Event count:</b> {}</p>"
        "<p><b>AS5600 present:</b> {}</p>"
        "<p><b>Raw angle:</b> {} ({:.2f} degrees)</p>"
        "<p><b>Wheel moving:</b> {}</p>"
        "<p><b>Wheel moved while active:</b> {}</p>"
        "<p>Webhook: <code>{}</code></p>"
        "</body></html>"
    ).format(
        ip,
        "YES" if mills_active else "NO",
        last_event,
        stack_event_count,
        "YES" if sensor_present else "NO",
        "unknown" if raw_angle is None else raw_angle,
        0.0 if angle_degrees is None else angle_degrees,
        "YES" if wheel_moving else "NO",
        "YES" if wheel_moved_while_active else "NO",
        STACK_MOVING_PATH,
    )


def handle_request(client):
    global mills_active, last_stack_event_ms, stack_event_count
    global wheel_moved_while_active, stable_since_ms
    global last_event_method, last_event_path, last_event_error
    global ota_reboot_pending, last_ota_status

    try:
        method, request_path, headers, initial_body, content_length = read_request(client)
        path = request_path.split("?", 1)[0]
        last_event_method = method
        last_event_path = path
        last_event_error = None

        if path == "/" and method == "GET":
            http_response(client, "200 OK", status_html(), "text/html")
        elif path == "/status" and method == "GET":
            http_response(client, "200 OK", status_json())
        elif path == STACK_MOVING_PATH and method in ("GET", "POST"):
            # Shelly may repeat a power condition while it remains true.
            # Treat only the inactive -> active transition as a new event.
            if not mills_active:
                mills_active = True
                wheel_moved_while_active = False
                stable_since_ms = None
                last_stack_event_ms = time.ticks_ms()
                stack_event_count += 1
                print("Shelly: Mills stack moving (event {})".format(stack_event_count))
            else:
                print("Shelly: repeated stack-moving event ignored")
            http_response(client, "200 OK", status_json())
        elif path == IDLE_PATH and method in ("GET", "POST"):
            mills_active = False
            wheel_moved_while_active = False
            print("Shelly: Mills idle")
            http_response(client, "200 OK", status_json())
        elif path == OTA_PATH and method == "POST":
            supplied_auth = headers.get("authorization", "")
            expected_auth = "Bearer " + OTA_TOKEN
            if not OTA_TOKEN:
                last_ota_status = "disabled: OTA_TOKEN missing"
                http_response(client, "503 Service Unavailable", '{"error":"OTA disabled"}')
            elif supplied_auth != expected_auth:
                last_ota_status = "rejected: unauthorized"
                http_response(client, "401 Unauthorized", '{"error":"unauthorized"}')
            else:
                try:
                    receive_ota_file(client, initial_body, content_length)
                    install_ota_file()
                    last_ota_status = "installed; reboot pending"
                    http_response(client, "200 OK", '{"ok":true,"rebooting":true}')
                    ota_reboot_pending = True
                except Exception as error:
                    safe_remove(OTA_TEMP_FILE)
                    last_ota_status = "failed: {}".format(error)
                    print("OTA ERROR:", error)
                    http_response(client, "400 Bad Request", '{"error":"OTA rejected"}')
        else:
            http_response(client, "404 Not Found", '{"error":"not found"}')
    except Exception as error:
        last_event_error = str(error)
        print("HTTP ERROR:", error)
        try:
            http_response(client, "400 Bad Request", '{"error":"bad request"}')
        except Exception:
            pass


def start_server():
    server = socket.socket()
    try:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    except Exception:
        pass
    server.bind(("0.0.0.0", WEB_PORT))
    server.listen(2)
    try:
        server.setblocking(False)
    except Exception:
        server.settimeout(0)
    print("HTTP server listening on port", WEB_PORT)
    return server


print("\nMills Pico preliminary webhook receiver")
wifi = connect_wifi()
server = None
if wifi.isconnected():
    server = start_server()
    print("Open http://{}/".format(wifi.ifconfig()[0]))
    print("Shelly webhook URL: http://{}/{}".format(
        wifi.ifconfig()[0], STACK_MOVING_PATH))
    print("Shelly idle URL: http://{}/{}".format(
        wifi.ifconfig()[0], IDLE_PATH))

last_wifi_retry_ms = time.ticks_ms()
last_sensor_sample_ms = time.ticks_ms()
while True:
    if server is not None:
        client = None
        try:
            client, _ = server.accept()
            try:
                client.settimeout(10)
            except Exception:
                pass
            handle_request(client)
        except Exception:
            pass
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
            if ota_reboot_pending:
                print("OTA installed; rebooting")
                time.sleep_ms(500)
                machine.reset()

    now = time.ticks_ms()
    if time.ticks_diff(now, last_sensor_sample_ms) >= AS5600_SAMPLE_MS:
        last_sensor_sample_ms = now
        update_sensor()

    if time.ticks_diff(now, last_wifi_retry_ms) >= WIFI_RETRY_MS:
        last_wifi_retry_ms = now
        if not wifi.isconnected():
            wifi = connect_wifi()
            if wifi.isconnected() and server is None:
                try:
                    server = start_server()
                except Exception as error:
                    print("Unable to start server:", error)

    gc.collect()
    time.sleep_ms(10)
