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


def rebuild_from_relationships(points, new_rest_raw):
    """Rebuild all rows from the saved circular step between each pair."""
    ordered = ["REST"] + [str(slot) for slot in range(1, 21)]
    missing = [point for point in ordered if point not in points]
    if missing:
        raise ValueError("missing calibration points: {}".format(", ".join(missing)))

    proposed = {"REST": dict(points["REST"], raw=new_rest_raw)}
    old_previous = int(points["REST"]["raw"])
    new_previous = new_rest_raw
    signed_steps = []
    for point in ordered[1:]:
        old_raw = int(points[point]["raw"])
        step = (old_raw - old_previous) % 4096
        if step > 2048:
            step -= 4096
        signed_steps.append(step)
        new_raw = (new_previous + step) % 4096
        proposed[point] = dict(
            points[point],
            raw=new_raw,
            degrees=round(new_raw * 360.0 / 4096.0, 2),
        )
        old_previous = old_raw
        new_previous = new_raw
    closing_step = (int(points["REST"]["raw"]) - old_previous) % 4096
    if closing_step > 2048:
        closing_step -= 4096
    signed_steps.append(closing_step)
    total_turn = sum(signed_steps)
    if abs(abs(total_turn) - 4096) > 64:
        raise ValueError(
            "adjacent relationships do not make one turn (total {} raw counts)"
            .format(total_turn))
    return proposed


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
        "--rebuild-from-relationships", "--rebase-all",
        dest="rebuild_from_relationships", action="store_true",
        help="rebuild all rows from saved circular steps between adjacent points")
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

    if args.rebuild_from_relationships:
        try:
            proposed = rebuild_from_relationships(points, args.rest_raw)
        except ValueError as error:
            print("Cannot rebuild table: {}".format(error), file=sys.stderr)
            return 1
        print_table(points, "Current calibration:")
        print_table(
            proposed,
            "Proposed relationship-based rebuild (REST delta {}):".format(offset))
        print("Adjacent relationships validated as one complete turn.")
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
    if args.rebuild_from_relationships:
        for point in sorted_points(proposed):
            if int(updated[point]["raw"]) != int(proposed[point]["raw"]):
                print(
                    "Verification failed: {} expected {}, got {}".format(
                        point, proposed[point]["raw"], updated[point]["raw"]),
                    file=sys.stderr)
                return 1
    print("Verified REST raw: {}".format(updated["REST"]["raw"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
