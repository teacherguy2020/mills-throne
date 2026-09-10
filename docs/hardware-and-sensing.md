# Hardware and Sensing Plan

## Shelly activity sensing

Replace the current smart outlet with a Shelly 1PM Gen4 UL and begin in observational mode. Capture complete cycles including:

```text
idle → credit/coin → mechanism search → record load → playing
     → reject/end → subsequent selections → final idle
```

Use collected power/current data to establish an idle threshold, an active/start threshold with hysteresis, start and stop debounce durations, and behavior during loading, rejecting, and multiple selections.

Do not choose production thresholds from the conceptual design alone. Shelly should send simple local events to Now-Playing after these values are established.

## Number-wheel identification

The preferred record-identification method is reading the existing Mills number-wheel shaft with a stationary AS5600 absolute magnetic angle sensor:

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
AS5600 SDA → Pico I2C SDA GPIO
AS5600 SCL → Pico I2C SCL GPIO
```

`OUT`, `DIR`, and `GPO` are probably unnecessary.

Before selecting this approach, measure the shaft travel. AS5600 is single-turn absolute sensing, so slots 1–20 must produce unique angles within one revolution (or another physically valid mapping). Calibrate measured raw angles for every position; do not assume equal spacing. Position 20 is also the home/off position and cannot identify record 20 by itself.

## Settle detection

A candidate selection is valid only when:

1. The Mills is known to be active.
2. The wheel has moved/searching.
3. The wheel stops.
4. The angle remains within one calibrated position window for the settle interval.

An initial diagnostic value of roughly 300–500 ms may be explored, but timing must be finalized from observed behavior.

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
