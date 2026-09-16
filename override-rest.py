#!/usr/bin/env python3
"""Safely override the Pico's REST calibration point.

The default operation changes REST only. Use --rebase-all only when the
sensor/magnet assembly was rotated as a rigid unit and all saved slot angles
should receive the same circular offset.
"""

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request


DEFAULT_PICO_IP = "10.0.0.7"


def request_json(url, method="GET"):
    request = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def fetch_calibration(base_url):
    return request_json(base_url + "/calibration")["points"]


def shifted(raw, offset):
    return (int(raw) + offset) % 4096


def sorted_points(points):
    return sorted(points, key=lambda point: (0, 0) if point == "REST" else (1, int(point)))


def print_table(points, title):
    print(title)
    for point in sorted_points(points):
        print("  {:>4}: raw {}".format(point, points[point]["raw"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rest_raw", type=int, help="new REST raw angle, 0-4095")
    parser.add_argument(
        "--pico-ip", default=os.environ.get("PICO_IP", DEFAULT_PICO_IP),
        help="Pico IP address (default: %(default)s)")
    parser.add_argument(
        "--rebase-all", action="store_true",
        help="also shift every saved slot by the current REST delta")
    parser.add_argument(
        "--apply", action="store_true",
        help="perform the change; without this flag, only show a preview")
    args = parser.parse_args()

    if not 0 <= args.rest_raw <= 4095:
        parser.error("rest_raw must be between 0 and 4095")

    base_url = "http://{}".format(args.pico_ip.rstrip("/"))
    try:
        points = fetch_calibration(base_url)
    except Exception as error:
        print("Unable to read Pico calibration: {}".format(error), file=sys.stderr)
        return 1

    if "REST" not in points:
        print("Pico calibration has no REST point", file=sys.stderr)
        return 1

    old_rest = int(points["REST"]["raw"])
    offset = (args.rest_raw - old_rest) % 4096

    if args.rebase_all:
        proposed = {
            point: dict(value, raw=shifted(value["raw"], offset))
            for point, value in points.items()
        }
        proposed["REST"] = dict(proposed["REST"], raw=args.rest_raw)
        print_table(points, "Current calibration:")
        print_table(proposed, "Proposed full-table rebase (offset {}):".format(offset))
        endpoint = "/calibration/shift?{}".format(urllib.parse.urlencode({
            "rest_raw": args.rest_raw,
        }))
    else:
        print("Current REST raw: {}".format(old_rest))
        print("Proposed REST raw: {}".format(args.rest_raw))
        print("Slots 1-20: unchanged")
        endpoint = "/calibration/override?{}".format(urllib.parse.urlencode({
            "point": "REST",
            "raw": args.rest_raw,
        }))

    if not args.apply:
        print("Preview only. Add --apply to make this change.")
        return 0

    try:
        result = request_json(base_url + endpoint, method="POST")
        print(json.dumps(result, indent=2))
        updated = fetch_calibration(base_url)
    except Exception as error:
        print("Calibration update failed: {}".format(error), file=sys.stderr)
        return 1

    if int(updated["REST"]["raw"]) != args.rest_raw:
        print("Verification failed: REST value did not persist", file=sys.stderr)
        return 1
    print("Verified REST raw: {}".format(updated["REST"]["raw"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
