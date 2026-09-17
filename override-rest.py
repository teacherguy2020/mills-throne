#!/usr/bin/env python3
"""Safely override the Pico's REST calibration point.

The default operation uses REST and slots 1-5 as a trusted local anchor, then
rebuilds later saved slots from their measured adjacent relationships. If later
slots are missing, the average of the most recent measured steps fills the
table from the first gap.
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
    """Rebuild the full table from first-five anchors and measured steps."""
    anchors = ["REST"] + [str(slot) for slot in range(1, 6)]
    missing = [point for point in anchors if point not in points]
    if missing:
        raise ValueError(
            "REST rebuild requires REST and slots 1-5; missing: {}".format(
                ", ".join(missing)))

    had_all_slots = all(
        str(slot) in points and not points[str(slot)].get("estimated")
        for slot in range(1, 21)
    )
    ordered = ["REST"] + [str(slot) for slot in range(1, 21)]
    proposed = {"REST": dict(points["REST"], raw=new_rest_raw)}
    old_previous = int(points["REST"]["raw"])
    new_previous = new_rest_raw
    signed_steps = []
    measured_steps = []
    extrapolating = False
    for point in ordered[1:]:
        if (point in points
                and not points[point].get("estimated")
                and not extrapolating):
            old_raw = int(points[point]["raw"])
            step = (old_raw - old_previous) % 4096
            if step > 2048:
                step -= 4096
            measured_steps.append(step)
            old_previous = old_raw
        else:
            if not measured_steps:
                raise ValueError("cannot calculate extrapolation step")
            extrapolating = True
            recent_steps = measured_steps[-5:]
            step = round(sum(recent_steps) / len(recent_steps))
        signed_steps.append(step)
        new_raw = (new_previous + step) % 4096
        if point in points:
            proposed[point] = dict(
                points[point],
                raw=new_raw,
                degrees=round(new_raw * 360.0 / 4096.0, 2),
            )
            if extrapolating:
                proposed[point]["estimated"] = True
        else:
            proposed[point] = {
                "raw": new_raw,
                "degrees": round(new_raw * 360.0 / 4096.0, 2),
                "relationship_rebuild": True,
                "estimated": True,
                "step_raw": step,
            }
        new_previous = new_raw

    # A complete-turn check is meaningful only when all 20 source slots exist.
    if had_all_slots:
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


def close_adjacent_pairs(points, limit=45):
    ordered = ["REST"] + [
        str(slot) for slot in range(1, 21)
        if str(slot) in points
    ]
    close = []
    for previous, point in zip(ordered, ordered[1:] + ["REST"]):
        distance = abs((int(points[point]["raw"]) - int(points[previous]["raw"]) + 2048) % 4096 - 2048)
        if distance <= limit:
            close.append((previous, point, distance))
    return close


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
        "--rest-only", action="store_true",
        help="change only REST and leave slots 1-20 unchanged")
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
    rebuild_mode = args.rebuild_from_relationships or not args.rest_only

    if rebuild_mode:
        try:
            proposed = rebuild_from_relationships(points, args.rest_raw)
        except ValueError as error:
            print("Cannot rebuild table: {}".format(error), file=sys.stderr)
            return 1
        print_table(points, "Current calibration:")
        print_table(
            proposed,
            "Proposed relationship-based rebuild (REST delta {}):".format(offset))
        if all(str(slot) in points for slot in range(1, 21)):
            print("Adjacent relationships validated as one complete turn.")
        else:
            print("Available relationships used; missing slots were filled from the recent measured-step average.")
        for previous, point, distance in close_adjacent_pairs(proposed):
            print(
                "WARNING: {} and {} are only {} raw counts apart; "
                "matching may be ambiguous.".format(previous, point, distance))
        endpoint = "/calibration/rebuild?{}".format(urllib.parse.urlencode({
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
    if rebuild_mode:
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
