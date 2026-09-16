"""Preliminary Mills activity webhook receiver for Pico 2 W.

The Shelly reports that the Mills record stack is moving by calling:

    GET or POST /integrations/mills/stack-moving

This version records the event, notifies Now-Playing on active/idle
transitions, samples the AS5600 for diagnostic use, provides a manual
calibration capture page, and reports settled calibrated selections.
Copy secrets.example.py to secrets.py and fill in the Wi-Fi settings.
"""

import gc
import machine
import os
import socket
import time

try:
    import ujson as json
except ImportError:
    import json

import network
from machine import I2C, Pin
from secrets import WIFI_SSID, WIFI_PASSWORD

try:
    from secrets import OTA_TOKEN
except ImportError:
    OTA_TOKEN = ""

try:
    from secrets import TRACK_KEY
except ImportError:
    TRACK_KEY = ""

try:
    from secrets import NOW_PLAYING_URL
except ImportError:
    NOW_PLAYING_URL = "http://10.0.0.4:3101"


WEB_PORT = 80
WIFI_RETRY_MS = 10000
STACK_MOVING_PATH = "/integrations/mills/stack-moving"
IDLE_PATH = "/integrations/mills/idle"
OTA_PATH = "/ota"
CALIBRATION_PATH = "/calibration"
CALIBRATION_CAPTURE_PATH = "/calibration/capture"
CALIBRATION_SHIFT_PATH = "/calibration/shift"
CALIBRATION_OVERRIDE_PATH = "/calibration/override"
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
# Shelly reports a threshold crossing, so do not end a Mills session on
# one brief low-power sample. This is provisional until AS5600 REST sensing
# becomes the authoritative end-of-session signal.
IDLE_CONFIRM_MS = 20000
CALIBRATION_FILE = "mills_calibration.json"
CALIBRATION_TEMP_FILE = "mills_calibration.new.json"
CALIBRATION_SAMPLE_COUNT = 15
CALIBRATION_SAMPLE_INTERVAL_MS = 80
# Accept occasional AS5600 glitches while requiring a strong steady majority.
CALIBRATION_INLIER_WINDOW_RAW = 32
CALIBRATION_MIN_INLIERS = 12
CALIBRATION_MATCH_WINDOW_RAW = 24
CALIBRATION_DISPLAY_STABLE_MS = 300
SELECTION_RETRY_MS = 5000

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
last_now_playing_event = None
pending_idle_since_ms = None
calibration_points = {}
selection_armed = False
last_selection_slot = None
last_selection_error = None
last_selection_attempt_ms = None

i2c = I2C(0, sda=Pin(4), scl=Pin(5), freq=100000)


def load_calibration():
    global calibration_points
    try:
        with open(CALIBRATION_FILE, "r") as calibration_file:
            loaded = json.load(calibration_file)
        if isinstance(loaded, dict):
            calibration_points = loaded
            print("Loaded calibration points:", ", ".join(sorted(calibration_points.keys())))
    except (OSError, ValueError, TypeError) as error:
        calibration_points = {}
        if not isinstance(error, OSError):
            print("Ignoring invalid calibration file:", error)


def save_calibration():
    """Write a complete calibration file before replacing the old one."""
    safe_remove(CALIBRATION_TEMP_FILE)
    with open(CALIBRATION_TEMP_FILE, "w") as calibration_file:
        json.dump(calibration_points, calibration_file)
        calibration_file.flush()
    safe_remove(CALIBRATION_FILE)
    os.rename(CALIBRATION_TEMP_FILE, CALIBRATION_FILE)


def sensor_flags(status):
    return {
        "detected": bool(status & 0x20),
        "weak": bool(status & 0x10),
        "strong": bool(status & 0x08),
    }


def circular_distance(first, second):
    delta = (first - second + 2048) % 4096 - 2048
    return abs(delta)


def read_sensor_sample():
    current_raw = read_u16(RAW_ANGLE_REGISTER) & 0x0FFF
    status = i2c.readfrom_mem(AS5600_ADDRESS, STATUS_REGISTER, 1)[0]
    agc = i2c.readfrom_mem(AS5600_ADDRESS, AGC_REGISTER, 1)[0]
    magnitude = read_u16(MAGNITUDE_REGISTER)
    return current_raw, status, agc, magnitude


def calibration_point_from_path(request_path):
    if "?" not in request_path:
        return None
    query = request_path.split("?", 1)[1]
    for item in query.split("&"):
        pair = item.split("=", 1)
        if len(pair) == 2 and pair[0] == "point":
            point = pair[1].upper()
            if point == "REST":
                return point
            try:
                slot = int(point)
                if 1 <= slot <= 20:
                    return str(slot)
            except ValueError:
                pass
    return None


def calibration_rest_raw_from_path(request_path):
    if "?" not in request_path:
        return None
    query = request_path.split("?", 1)[1]
    for item in query.split("&"):
        pair = item.split("=", 1)
        if len(pair) == 2 and pair[0] == "rest_raw":
            try:
                raw = int(pair[1])
                if 0 <= raw <= 4095:
                    return raw
            except ValueError:
                pass
    return None


def calibration_source_rest_raw_from_path(request_path):
    if "?" not in request_path:
        return None
    query = request_path.split("?", 1)[1]
    for item in query.split("&"):
        pair = item.split("=", 1)
        if len(pair) == 2 and pair[0] == "from_rest_raw":
            try:
                raw = int(pair[1])
                if 0 <= raw <= 4095:
                    return raw
            except ValueError:
                pass
    return None


def calibration_raw_from_path(request_path):
    if "?" not in request_path:
        return None
    query = request_path.split("?", 1)[1]
    for item in query.split("&"):
        pair = item.split("=", 1)
        if len(pair) == 2 and pair[0] == "raw":
            try:
                raw = int(pair[1])
                if 0 <= raw <= 4095:
                    return raw
            except ValueError:
                pass
    return None


def calibration_sort_key(point):
    if point == "REST":
        return (0, 0)
    try:
        return (1, int(point))
    except ValueError:
        return (2, point)


def capture_calibration_point(point):
    """Capture a stable sample set for REST or one physical slot."""
    global raw_angle, angle_degrees, sensor_status, agc_value, magnitude_value

    if AS5600_ADDRESS not in i2c.scan():
        raise OSError("AS5600 not detected")

    samples = []
    statuses = []
    agcs = []
    magnitudes = []
    for index in range(CALIBRATION_SAMPLE_COUNT):
        sample_raw, sample_status, sample_agc, sample_magnitude = read_sensor_sample()
        samples.append(sample_raw)
        statuses.append(sample_status)
        agcs.append(sample_agc)
        magnitudes.append(sample_magnitude)
        if index + 1 < CALIBRATION_SAMPLE_COUNT:
            time.sleep_ms(CALIBRATION_SAMPLE_INTERVAL_MS)

    ordered = sorted(samples)
    median_raw = ordered[len(ordered) // 2]
    inliers = [
        sample for sample in samples
        if circular_distance(sample, median_raw) <= CALIBRATION_INLIER_WINDOW_RAW
    ]
    if len(inliers) < CALIBRATION_MIN_INLIERS:
        raise ValueError(
            "angle unstable; only {}/{} samples agreed (full spread {} raw counts)".format(
                len(inliers), len(samples), max(samples) - min(samples)))

    # Measure the spread of agreeing samples, accounting for 4095 -> 0.
    inlier_ordered = sorted(inliers)
    gaps = [
        inlier_ordered[index + 1] - inlier_ordered[index]
        for index in range(len(inlier_ordered) - 1)
    ]
    gaps.append(inlier_ordered[0] + 4096 - inlier_ordered[-1])
    observed_spread = 4096 - max(gaps)

    status = statuses[-1]
    raw_angle = median_raw
    angle_degrees = median_raw * 360.0 / 4096.0
    sensor_status = status
    agc_value = agcs[-1]
    magnitude_value = magnitudes[-1]
    flags = sensor_flags(status)
    calibration_points[point] = {
        "raw": median_raw,
        "degrees": round(angle_degrees, 2),
        "sample_count": len(samples),
        "min_raw": min(samples),
        "max_raw": max(samples),
        "spread_raw": observed_spread,
        "inlier_count": len(inliers),
        "outlier_count": len(samples) - len(inliers),
        "detected": flags["detected"],
        "weak": flags["weak"],
        "strong": flags["strong"],
        "agc": agcs[-1],
        "magnitude": magnitudes[-1],
    }
    save_calibration()
    return calibration_points[point]


def shift_calibration_to_rest(new_rest_raw, source_rest_raw=None):
    """Rotate the table from a known REST point to new_rest_raw."""
    if "REST" not in calibration_points:
        raise ValueError("REST calibration point is missing")
    if source_rest_raw is None:
        old_rest_raw = int(calibration_points["REST"]["raw"])
    else:
        old_rest_raw = source_rest_raw
    offset = (new_rest_raw - old_rest_raw) % 4096
    for point, value in calibration_points.items():
        if point == "REST":
            continue
        old_raw = int(value["raw"])
        value["raw"] = (old_raw + offset) % 4096
        value["degrees"] = round(value["raw"] * 360.0 / 4096.0, 2)
        for key in ("min_raw", "max_raw"):
            if key in value:
                value[key] = (int(value[key]) + offset) % 4096
        value["offset_raw"] = offset
    calibration_points["REST"]["raw"] = new_rest_raw
    calibration_points["REST"]["degrees"] = round(new_rest_raw * 360.0 / 4096.0, 2)
    calibration_points["REST"]["offset_raw"] = offset
    save_calibration()
    return old_rest_raw, offset


def override_calibration_point(point, new_raw):
    if point not in calibration_points:
        raise ValueError("calibration point not found")
    value = calibration_points[point]
    value["raw"] = new_raw
    value["degrees"] = round(new_raw * 360.0 / 4096.0, 2)
    value["manual_override"] = True
    save_calibration()
    return value


def calibrated_position():
    """Return the nearest settled calibration point."""
    if raw_angle is None or not calibration_points:
        return None, None, "unknown"
    if wheel_moving or stable_since_ms is None:
        return None, None, "moving/not settled"
    if time.ticks_diff(time.ticks_ms(), stable_since_ms) < CALIBRATION_DISPLAY_STABLE_MS:
        return None, None, "settling"

    nearest_point = None
    nearest_distance = None
    for point, value in calibration_points.items():
        try:
            point_raw = int(value["raw"])
        except (KeyError, TypeError, ValueError):
            continue
        distance = circular_distance(raw_angle, point_raw)
        if nearest_distance is None or distance < nearest_distance:
            nearest_point = point
            nearest_distance = distance

    if nearest_point is None:
        return None, None, "unknown"
    if nearest_distance > CALIBRATION_MATCH_WINDOW_RAW:
        return None, nearest_distance, "no match"
    return nearest_point, nearest_distance, "match"


def process_selection():
    """Report one newly settled physical slot after movement."""
    global selection_armed, last_selection_slot, last_selection_error
    global last_selection_attempt_ms

    if not mills_active or not selection_armed:
        return
    now = time.ticks_ms()
    if (last_selection_attempt_ms is not None
            and time.ticks_diff(now, last_selection_attempt_ms) < SELECTION_RETRY_MS):
        return
    position, _, position_state = calibrated_position()
    if position_state != "match" or position == "REST":
        return

    try:
        slot = int(position)
        last_selection_attempt_ms = now
        notify_now_playing("/integrations/mills/selection", {"slot": slot})
        last_selection_slot = slot
        last_selection_error = None
        selection_armed = False
        print("Mills selection reported:", slot)
    except Exception as error:
        last_selection_error = "selection failed: {}".format(error)
        print(last_selection_error)


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


def send_all(client, data):
    sent_total = 0
    while sent_total < len(data):
        sent = client.send(data[sent_total:])
        if not sent:
            raise OSError("socket send failed")
        sent_total += sent


def http_response(client, status, body, content_type="application/json"):
    payload = body.encode()
    header = (
        "HTTP/1.1 {}\r\n"
        "Content-Type: {}; charset=utf-8\r\n"
        "Content-Length: {}\r\n"
        "Cache-Control: no-store\r\n"
        "Connection: close\r\n\r\n"
    ).format(status, content_type, len(payload))
    send_all(client, header.encode())
    send_all(client, payload)


def parse_http_url(url):
    text = str(url).strip().rstrip("/")
    if not text.startswith("http://"):
        raise ValueError("Now-Playing URL must use http://")
    authority_and_path = text[7:]
    slash = authority_and_path.find("/")
    authority = authority_and_path if slash < 0 else authority_and_path[:slash]
    if ":" in authority:
        host, port_text = authority.rsplit(":", 1)
        port = int(port_text)
    else:
        host, port = authority, 80
    if not host:
        raise ValueError("Now-Playing URL has no host")
    return host, port


def notify_now_playing(path, payload=None):
    """Notify Now-Playing and require a successful HTTP response."""
    host, port = parse_http_url(NOW_PLAYING_URL)
    address = socket.getaddrinfo(host, port)[0][-1]
    client = socket.socket()
    try:
        client.settimeout(4)
        client.connect(address)
        auth = ""
        if TRACK_KEY:
            auth = "X-Track-Key: {}\r\n".format(TRACK_KEY)
        if payload is None:
            body = b""
            content_type = ""
        else:
            body = json.dumps(payload).encode()
            content_type = "Content-Type: application/json\r\n"
        request = (
            "POST {} HTTP/1.1\r\n"
            "Host: {}\r\n"
            "{}"
            "{}"
            "Content-Length: {}\r\n"
            "Connection: close\r\n\r\n"
        ).format(path, host, auth, content_type, len(body)).encode()
        send_all(client, request)
        if body:
            send_all(client, body)
        response = client.recv(512)
        if not response:
            raise OSError("empty Now-Playing response")
        first_line = response.split(b"\r\n", 1)[0].decode()
        parts = first_line.split()
        if len(parts) < 2 or not parts[1].isdigit():
            raise OSError("malformed Now-Playing response")
        status_code = int(parts[1])
        if status_code < 200 or status_code >= 300:
            raise OSError("Now-Playing returned HTTP {}".format(status_code))
    finally:
        client.close()


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
    global stable_since_ms, selection_armed

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
                selection_armed = True
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
    position, position_distance, position_state = calibrated_position()
    return (
        '{{"mills_active":{},"last_stack_event_ms":{},'
        '"stack_event_count":{},"ip":{},"sensor_present":{},'
        '"raw_angle":{},"angle_degrees":{},"wheel_moving":{},'
        '"wheel_moved_while_active":{},"stable_ms":{},'
        '"sensor_status":"{}","agc":{},"magnitude":{},'
        '"ota_status":"{}","last_now_playing_event":{},'
        '"idle_pending_ms":{},"calibration_points":{},'
        '"calibrated_position":{},"calibrated_distance_raw":{},'
        '"calibrated_position_state":"{}","selection_armed":{},'
        '"last_selection_slot":{},"last_selection_error":{}}}'
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
        "null" if last_now_playing_event is None else '"{}"'.format(last_now_playing_event),
        "null" if pending_idle_since_ms is None else time.ticks_diff(time.ticks_ms(), pending_idle_since_ms),
        len(calibration_points),
        "null" if position is None else '"{}"'.format(position),
        "null" if position_distance is None else position_distance,
        position_state,
        "true" if selection_armed else "false",
        "null" if last_selection_slot is None else last_selection_slot,
        "null" if last_selection_error is None else '"{}"'.format(last_selection_error),
    )


def status_html():
    ip = wifi.ifconfig()[0] if wifi and wifi.isconnected() else "offline"
    last_event = "never" if last_stack_event_ms is None else "{} ms ago".format(
        time.ticks_diff(time.ticks_ms(), last_stack_event_ms)
    )
    calibrated = "none" if not calibration_points else ", ".join(
        sorted(calibration_points.keys(), key=calibration_sort_key))
    position, position_distance, position_state = calibrated_position()
    if position_state == "match":
        current_position = "REST" if position == "REST" else "slot {}".format(position)
        current_position += " ({} raw counts away)".format(position_distance)
    elif position_state == "no match":
        current_position = "no calibrated match (nearest is {} raw counts away)".format(
            position_distance)
    else:
        current_position = position_state
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta http-equiv='refresh' content='2'>"
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
        "<p><b>Magnet status:</b> {}</p>"
        "<p><b>AGC:</b> {}</p>"
        "<p><b>Magnitude:</b> {}</p>"
        "<p><b>Angle stable for:</b> {} ms</p>"
        "<p><b>Idle confirmation:</b> {} </p>"
        "<p><b>Calibrated points:</b> {}</p>"
        "<p><b>Current calibrated position:</b> {}</p>"
        "<p><b>Selection reporting armed:</b> {}</p>"
        "<p><b>Last selection reported:</b> {}</p>"
        "<p><a href='/calibrate'>Open calibration page</a></p>"
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
        sensor_status_text(),
        "unknown" if agc_value is None else agc_value,
        "unknown" if magnitude_value is None else magnitude_value,
        "unknown" if stable_since_ms is None else time.ticks_diff(time.ticks_ms(), stable_since_ms),
        "pending" if pending_idle_since_ms is not None else "not pending",
        calibrated,
        current_position,
        "YES" if selection_armed else "NO",
        "none" if last_selection_slot is None else "slot {}".format(last_selection_slot),
        STACK_MOVING_PATH,
    )


def calibration_json():
    return json.dumps({"points": calibration_points})


def calibration_html():
    buttons = "<button onclick=\"capture('REST')\">Capture REST</button>"
    for slot in range(1, 21):
        buttons += " <button onclick=\"capture('{}')\">Capture {}</button>".format(slot, slot)

    rows = ""
    for point in sorted(calibration_points.keys(), key=calibration_sort_key):
        value = calibration_points[point]
        quality = "weak" if value.get("weak") else "ok"
        rows += (
            "<tr><td>{}</td><td>{}</td><td>{:.2f}</td><td>{}</td>"
            "<td>{}</td><td>{}</td><td>{}</td>"
            "<td><input id='raw-{}' type='number' min='0' max='4095' step='1' value='{}'>"
            " <button onclick=\"savePoint('{}')\">Save</button>"
            " <button onclick=\"clearPoint('{}')\">Clear</button></td></tr>"
        ).format(
            point,
            value.get("raw", "?"),
            value.get("degrees", 0.0),
            value.get("spread_raw", "?"),
            value.get("magnitude", "?"),
            quality,
            value.get("sample_count", "?"),
            point,
            value.get("raw", ""),
            point,
            point,
        )
    if not rows:
        rows = "<tr><td colspan='8'>No calibration points captured.</td></tr>"
    current_rest_raw = calibration_points.get("REST", {}).get("raw", "")
    current_reading = (
        "<strong>Raw angle:</strong> {} &nbsp; "
        "<strong>Degrees:</strong> {}&deg;<br>"
        "Wheel moving: {}; stable: {} ms; "
        "magnet: {}; AGC: {}; magnitude: {}"
    ).format(
        "unknown" if raw_angle is None else raw_angle,
        "unknown" if angle_degrees is None else "{:.2f}".format(angle_degrees),
        "YES" if wheel_moving else "NO",
        "unknown" if stable_since_ms is None else time.ticks_diff(
            time.ticks_ms(), stable_since_ms),
        sensor_status_text(),
        "unknown" if agc_value is None else agc_value,
        "unknown" if magnitude_value is None else magnitude_value,
    )

    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Mills calibration</title></head><body>"
        "<h1>Mills angle calibration</h1>"
        "<p>Hold the mechanism completely still, then capture the current point."
        " REST is separate from slot 20.</p>"
        "<h2>Current AS5600 angle</h2>"
        "<p id='currentReading'>{}</p>"
        "<button onclick='location.reload()'>Refresh current reading</button>"
        "<h2>REST override</h2>"
        "<p>Enter a new settled REST raw angle to rotate the existing table."
        " Use this only when the sensor/magnet geometry has not changed.</p>"
        "<label>REST raw: <input id='restRaw' type='number' min='0' max='4095'"
        " step='1' value='{}'></label>"
        " <button onclick='overrideRest()'>Apply REST override</button>"
        "<p>{}</p>"
        "<p id='message'></p>"
        "<table border='1' cellpadding='4'><tr><th>Point</th><th>Raw</th>"
        "<th>Degrees</th><th>Spread</th><th>Magnitude</th><th>Quality</th>"
        "<th>Samples</th><th>Action</th></tr>{}</table>"
        "<p><a href='/'>Back to status</a></p>"
        "<script>"
        "async function capture(point) {{"
        " const message=document.getElementById('message');"
        " message.textContent='Capturing '+point+'; keep it still...';"
        " try {{ const response=await fetch('/calibration/capture?point='+point,{{method:'POST'}});"
        " const data=await response.json();"
        " if (!response.ok) throw new Error(data.error || 'capture failed');"
        " message.textContent='Captured '+point+' at raw '+data.calibration.raw;"
        " setTimeout(()=>location.reload(),500);"
        " }} catch (error) {{ message.textContent='ERROR: '+error; }}"
        "}}"
        "async function clearPoint(point) {{"
        " if (!confirm('Clear calibration point '+point+'?')) return;"
        " const response=await fetch('/calibration/clear?point='+point,{{method:'POST'}});"
        " if (!response.ok) {{ document.getElementById('message').textContent='ERROR: clear failed'; return; }}"
        " location.reload();"
        "}}"
        "async function savePoint(point) {{"
        " const message=document.getElementById('message');"
        " const input=document.getElementById('raw-'+point);"
        " const raw=Number(input.value);"
        " if (!Number.isInteger(raw) || raw < 0 || raw > 4095) {{"
        " message.textContent='ERROR: raw angle must be an integer from 0 to 4095'; return; }}"
        " message.textContent='Saving '+point+' at raw '+raw+'...';"
        " try {{ const response=await fetch('/calibration/override?point='+encodeURIComponent(point)+'&raw='+raw,{{method:'POST'}});"
        " const data=await response.json();"
        " if (!response.ok) throw new Error(data.error || 'save failed');"
        " message.textContent='Saved '+point+' at raw '+data.calibration.raw;"
        " setTimeout(()=>location.reload(),500);"
        " }} catch (error) {{ message.textContent='ERROR: '+error; }}"
        "}}"
        "async function overrideRest() {{"
        " const message=document.getElementById('message');"
        " const input=document.getElementById('restRaw');"
        " const raw=Number(input.value);"
        " if (!Number.isInteger(raw) || raw < 0 || raw > 4095) {{"
        " message.textContent='ERROR: REST raw must be an integer from 0 to 4095'; return; }}"
        " if (!confirm('Rotate the existing calibration table to REST raw '+raw+'?')) return;"
        " message.textContent='Applying REST override...';"
        " try {{ const response=await fetch('/calibration/shift?rest_raw='+raw,{{method:'POST'}});"
        " const data=await response.json();"
        " if (!response.ok) throw new Error(data.error || 'REST override failed');"
        " message.textContent='REST updated to raw '+data.new_rest_raw+'; offset '+data.offset_raw;"
        " setTimeout(()=>location.reload(),700);"
        " }} catch (error) {{ message.textContent='ERROR: '+error; }}"
        "}}"
        "</script></body></html>"
    ).format(current_rest_raw, current_reading, buttons, rows)


def handle_request(client):
    global mills_active, last_stack_event_ms, stack_event_count
    global wheel_moved_while_active, stable_since_ms
    global last_event_method, last_event_path, last_event_error
    global ota_reboot_pending, last_ota_status, last_now_playing_event
    global pending_idle_since_ms, selection_armed, last_selection_slot
    global last_selection_error, last_selection_attempt_ms

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
        elif path == CALIBRATION_PATH and method == "GET":
            http_response(client, "200 OK", calibration_json())
        elif path == "/calibrate" and method == "GET":
            http_response(client, "200 OK", calibration_html(), "text/html")
        elif path == CALIBRATION_OVERRIDE_PATH and method == "POST":
            point = calibration_point_from_path(request_path)
            new_raw = calibration_raw_from_path(request_path)
            if point is None or new_raw is None:
                http_response(
                    client,
                    "400 Bad Request",
                    '{"error":"point must be REST or 1-20 and raw must be 0-4095"}',
                )
            else:
                try:
                    overridden = override_calibration_point(point, new_raw)
                    http_response(client, "200 OK", json.dumps({
                        "ok": True,
                        "point": point,
                        "calibration": overridden,
                    }))
                    print("Calibration overridden:", point, new_raw)
                except Exception as error:
                    print("CALIBRATION OVERRIDE ERROR:", error)
                    http_response(client, "404 Not Found", json.dumps({"error": str(error)}))
        elif path == CALIBRATION_SHIFT_PATH and method == "POST":
            new_rest_raw = calibration_rest_raw_from_path(request_path)
            source_rest_raw = calibration_source_rest_raw_from_path(request_path)
            if new_rest_raw is None:
                http_response(
                    client,
                    "400 Bad Request",
                    '{"error":"rest_raw must be 0-4095"}',
                )
            else:
                try:
                    old_rest_raw, offset = shift_calibration_to_rest(
                        new_rest_raw, source_rest_raw)
                    http_response(client, "200 OK", json.dumps({
                        "ok": True,
                        "old_rest_raw": old_rest_raw,
                        "new_rest_raw": new_rest_raw,
                        "offset_raw": offset,
                    }))
                    print(
                        "Calibration shifted: REST {} -> {} (offset {})".format(
                            old_rest_raw, new_rest_raw, offset))
                except Exception as error:
                    print("CALIBRATION SHIFT ERROR:", error)
                    http_response(client, "409 Conflict", json.dumps({"error": str(error)}))
        elif path == CALIBRATION_CAPTURE_PATH and method == "POST":
            point = calibration_point_from_path(request_path)
            if point is None:
                http_response(client, "400 Bad Request", '{"error":"point must be REST or 1-20"}')
            else:
                try:
                    captured = capture_calibration_point(point)
                    http_response(client, "200 OK", json.dumps({
                        "ok": True,
                        "point": point,
                        "calibration": captured,
                    }))
                    print("Calibration captured:", point, captured)
                except Exception as error:
                    print("CALIBRATION ERROR:", error)
                    http_response(client, "409 Conflict", json.dumps({"error": str(error)}))
        elif path == "/calibration/clear" and method == "POST":
            point = calibration_point_from_path(request_path)
            if point is None:
                http_response(client, "400 Bad Request", '{"error":"point must be REST or 1-20"}')
            elif point in calibration_points:
                del calibration_points[point]
                save_calibration()
                print("Calibration cleared:", point)
                http_response(client, "200 OK", json.dumps({"ok": True, "point": point}))
            else:
                http_response(client, "404 Not Found", '{"error":"calibration point not found"}')
        elif path == STACK_MOVING_PATH and method in ("GET", "POST"):
            # Shelly may repeat a power condition while it remains true.
            # Treat only the inactive -> active transition as a new event,
            # but let renewed activity cancel a pending idle confirmation.
            if mills_active:
                if pending_idle_since_ms is not None:
                    pending_idle_since_ms = None
                    print("Shelly: renewed activity; pending idle canceled")
                else:
                    print("Shelly: repeated stack-moving event ignored")
            else:
                try:
                    notify_now_playing("/integrations/mills/start")
                    mills_active = True
                    pending_idle_since_ms = None
                    wheel_moved_while_active = False
                    stable_since_ms = None
                    selection_armed = False
                    last_selection_slot = None
                    last_selection_error = None
                    last_selection_attempt_ms = None
                    last_stack_event_ms = time.ticks_ms()
                    stack_event_count += 1
                    last_now_playing_event = "start"
                    print("Shelly: Mills stack moving (event {})".format(stack_event_count))
                except Exception as error:
                    last_event_error = "Now-Playing start failed: {}".format(error)
                    last_now_playing_event = "start failed"
                    print(last_event_error)
                    http_response(client, "502 Bad Gateway", '{"error":"Now-Playing start failed"}')
                    return
            http_response(client, "200 OK", status_json())
        elif path == IDLE_PATH and method in ("GET", "POST"):
            if mills_active:
                if pending_idle_since_ms is None:
                    pending_idle_since_ms = time.ticks_ms()
                    print("Shelly: idle candidate; waiting for confirmation")
                else:
                    print("Shelly: repeated idle event ignored; confirmation pending")
            else:
                print("Shelly: repeated idle event ignored")
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


def process_pending_idle():
    """End the session only after low-power state remains long enough."""
    global mills_active, pending_idle_since_ms, wheel_moved_while_active
    global selection_armed
    global last_event_error, last_now_playing_event

    if not mills_active or pending_idle_since_ms is None:
        return
    if time.ticks_diff(time.ticks_ms(), pending_idle_since_ms) < IDLE_CONFIRM_MS:
        return

    try:
        notify_now_playing("/integrations/mills/stop")
        mills_active = False
        pending_idle_since_ms = None
        wheel_moved_while_active = False
        selection_armed = False
        last_now_playing_event = "stop"
        last_event_error = None
        print("Shelly: Mills idle confirmed")
    except Exception as error:
        # Keep Mills active through a transient Now-Playing outage and retry
        # after another confirmation interval.
        pending_idle_since_ms = time.ticks_ms()
        last_event_error = "Now-Playing stop failed: {}".format(error)
        last_now_playing_event = "stop failed"
        print(last_event_error)


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
load_calibration()
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
        process_selection()

    process_pending_idle()

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
