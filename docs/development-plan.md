# Phased Development Plan

## Phase 1 — Harmony source switching

Add reusable Harmony Hub websocket support to Now-Playing and verify Denon → Phono (Mills) and Denon → Aux 1 (moOde).

## Phase 2 — Observe Mills power

Install the Shelly 1PM Gen4 UL, log several full Mills cycles, and determine measured thresholds, hysteresis, and debounce behavior. Keep installation observational until the profile is understood.

## Phase 3 — Activity orchestration

Implement and test `/integrations/mills/start` and `/integrations/mills/stop` with the MPD resume invariant and Denon switching. Confirm duplicate events are harmless.

## Phase 4 — Mechanical inspection

Inspect the number-wheel shaft, determine total rotation, and document magnet coupling, air gap, and stationary sensor mounting geometry without interfering with the mechanism.

## Phase 5 — Sensor prototype

Prototype AS5600 + magnet + Pico diagnostic firmware/web page showing raw angle, degrees, movement/stopped state, stable duration, and provisional calibrated slot.

## Phase 6 — Calibration and settle logic

Measure and store all 20 Mills positions, define tolerance windows, and implement wheel movement and settle detection. Validate home/off position handling.

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
