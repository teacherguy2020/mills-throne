# Hardware and Sensing Plan

## Shelly activity sensing

The Shelly 1PM Gen4 UL replaces the current smart outlet and begins in observational mode. Capture complete cycles including:

```text
idle → credit/coin → mechanism search → record load → playing
     → reject/end → subsequent selections → final idle
```

Initial observed values are approximately:

```text
lights off, idle       ~7 W
lights on, idle        ~53 W
record playing         ~70 W
stack/motor moving     >200 W
```

The current temporary Shelly thresholds are approximately `>55 W` for
activity and `<50 W` for idle. Pico-side idle debounce smooths short dips;
these remain test values, not production values. Continue capturing behavior
during loading, rejecting, and multiple selections before finalizing anything.

Do not choose production thresholds from the conceptual design alone. Shelly may provide independent confirmation, but the AS5600/Pico may ultimately become the primary mechanism-state signal.

## Number-wheel identification

The preferred record-identification method is reading the existing Mills selector shaft with a stationary AS5600 absolute magnetic angle sensor. The wheel’s original screw does not rotate; the opposite end of the shaft is exposed and is the current magnet mounting point:

```text
Mills number-wheel shaft
  → small diametrically magnetized magnet
  → stationary AS5600
  → I2C
  → Pico 2 W / Pico W
  → Wi-Fi
  → Now-Playing
```

Typical connections:

```text
AS5600 VCC → Pico 3.3V
AS5600 GND → Pico GND
AS5600 SDA → Pico GP4 (physical pin 6)
AS5600 SCL → Pico GP5 (physical pin 7)
```

`OUT`, `DIR`, and `GPO` are unnecessary for this design. The AS5600 is bench-tested successfully at I²C address `0x36`; the current diagnostic program reports raw angle, degrees, movement, stable time, magnet status, AGC, and magnitude.

The final mount must preserve magnet centering and air gap. Use a rigid, adjustable nonmagnetic bracket; temporary plastic spacing is suitable for bench testing, but the magnet must not touch the sensor during rotation. AS5600 is single-turn absolute sensing, so record actual installed raw values for REST and positions 1–20 rather than assuming equal spacing.

The larger gap between positions 20 and 1 is the Mills REST position. A stable angle at 20 during reset is not slot 20; a stable 20 reached after downward search may be slot 20. Direction and phase history are required if the mechanism passes through 20 more than once.

## Settle detection

A candidate selection is valid only when:

1. The Mills is known to be active.
2. The wheel has moved/searching.
3. The wheel stops.
4. The angle remains within one calibrated position window for the settle interval.

An initial diagnostic value of roughly 300–500 ms may be explored, but timing must be finalized from observed behavior.

## Manual calibration capture

The Pico exposes a temporary calibration page at:

```text
http://<pico-ip>/calibrate
```

With the mechanism stopped, capture the distinct REST gap first, then capture physical positions 1–20 individually. The Pico takes multiple samples and stores the median raw angle along with the sample spread and magnetic diagnostics in its local `mills_calibration.json` file. REST is stored as `REST`, not as slot 0, and remains distinct from slot 20.

The calibration page's REST override uses REST and slots 1–5 as the trusted
anchor. It preserves their measured uneven relationships, carries forward
measured relationships for later saved slots, and fills any trailing missing
slots using the average of the most recent measured steps. Generated rows are marked estimated.
The Mac-side `override-rest.py` script previews this operation and applies it
only with `--apply`:

```bash
./override-rest.py <new-rest-raw>
./override-rest.py <new-rest-raw> --apply
```

If the physical geometry changed, use `--rest-only` instead to change only REST, or use individual row overrides/fresh captures:

```bash
./override-rest.py <new-rest-raw> --rest-only --apply
```

The script calculates the first-five relationships from the Pico's current
saved table and does not use a hard-coded historical REST value. If all 20
slots exist, later slots retain their measured relationships. If calibration is
partial, the most recent five measured steps complete the missing tail.

Each measured step uses the signed shortest circular difference in raw counts
(`-2048..2047`), and each point is reconstructed cumulatively with modulo-4096
wrapping. A complete-turn check is applied when all 20 source slots exist.

Calibration may be captured while the sensor reports a weak field for exploratory purposes, but those values are provisional. The current Pico has REST plus all 20 slots stored, with generally 0–2 raw-count inlier spread per capture; the AS5600 still reports `weak=YES` and occasional outliers. Before production use, improve the mount until the field is detected and stable without `weak` or `strong` status, then repeat the affected captures. The Pico now uses saved points for provisional display and settled-slot reporting, and sends the matched slot to Now-Playing for validation against real Mills cycles.

## Optional tray sensor

The V-156-1C25-style roller-lever SPDT microswitches are dry-contact switches, not relays. A future Pico input may use:

```text
Pico GPIO → microswitch → GND
```

with the internal pull-up enabled. A gently actuated switch at the tray/linkage could provide an independent `RECORD_AT_TURNTABLE` signal. Combined signals would be:

- Shelly: whole-machine activity,
- AS5600: which record position,
- tray switch: physical arrival at the turntable.

## Alternative

Stack height could encode the 20 positions using Hall sensors, a linear sensor, or optical sensing. Twenty Hall sensors are expected to add excessive wiring and mounting complexity, so shaft-angle sensing remains preferred pending mechanical inspection.

<!-- Last updated: 2026-09-16 -->
