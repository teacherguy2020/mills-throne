# Phased Development Plan

## Phase 1 — Harmony source switching

Add reusable Harmony Hub websocket support to Now-Playing and verify Denon → Phono (Mills) and Denon → Aux 1 (moOde).

## Phase 2 — Observe Mills power

Install the Shelly 1PM Gen4 UL, log several full Mills cycles, and determine measured thresholds, hysteresis, and debounce behavior. Keep installation observational until the profile is understood.

## Phase 3 — Activity orchestration

Implement and test `/integrations/mills/start` and `/integrations/mills/stop` with the MPD resume invariant and Denon switching. Confirm duplicate events are harmless.

## Phase 4 — Mechanical inspection and installation

The selector-wheel screw is stationary; use the exposed opposite shaft end for the magnet. Mount the AS5600 on a rigid adjustable bracket without interfering with the mechanism. Verify the shaft’s actual rotation and the REST gap between positions 20 and 1.

## Phase 5 — Sensor prototype and diagnostics

The Pico bench test and integrated diagnostic program are complete. The integrated program samples raw angle, degrees, movement/stopped state, stable duration, magnet status, AGC, and magnitude while accepting Shelly activity/idle webhooks. OTA updates are implemented and tested so the mounted assembly can be updated without disturbing alignment.

## Phase 6 — Calibration and settle logic

Measure and store REST plus all 20 Mills positions, define tolerance windows, and implement wheel movement/phase and settle detection. Validate whether the shaft passes through position 20 more than once during reset/search and explicitly distinguish REST from slot 20.

## Phase 7 — Metadata integration

Implement `/integrations/mills/selection`, map physical slots to digital-library records, and expose corresponding metadata/artwork to Now-Playing clients.

## Phase 8 — Optional tray confirmation

Add a tray microswitch if it improves confidence in physical record arrival and helps distinguish movement states.

## Acceptance goals

- The original Mills mechanism remains fully authoritative.
- Normal Mills operation never depends on cloud services.
- MPD pauses/resumes only according to the captured pre-Mills state.
- Denon source changes are reliable and repeatable.
- Duplicate Shelly events do not corrupt integration state.
- Record IDs are reported only after actual mechanical settling.
- Metadata/artwork tracks the physical record while Mills supplies the audio.
- Final idle detection waits for true sustained idle, not a transient reject/search interval.

## Current physical milestone

The Shelly webhook path and AS5600 bench test are working. The next meaningful milestone is mounting the sensor/magnet assembly and collecting synchronized AS5600 and Shelly observations for REST, positions 1–20, and complete single- and multiple-record sessions.

<!-- Last updated: 2026-09-15 -->
