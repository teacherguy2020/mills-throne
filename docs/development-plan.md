# Phased Development Plan

## Phase 1 — Harmony source switching — implemented

Now-Playing contains a reusable local Harmony Hub WebSocket client and
authenticated Mills source-switching routes. Verify Denon → Phono (Mills) and
Denon → Aux 1 (moOde) with the installed hardware.

## Phase 2 — Observe Mills power — initial implementation complete

The Shelly 1PM Gen4 UL is installed and providing activity/idle webhook
events. Temporary thresholds of approximately `>55 W` and `<50 W` are in use,
with Pico-side debounce. Continue logging complete cycles before treating
these values as production thresholds.

## Phase 3 — Activity orchestration — implemented

The Pico accepts Shelly activity/idle transitions and forwards only the first
active and confirmed final idle transition to Now-Playing. The routes switch
the Denon and are idempotent/retryable. The current temporary Shelly
thresholds are approximately `>55 W` and `<50 W`, with Pico-side idle
debounce. Now-Playing's Mills selection route is deployed for testing.

## Phase 4 — Mechanical inspection and installation

The selector-wheel screw is stationary; use the exposed opposite shaft end for the magnet. Mount the AS5600 on a rigid adjustable bracket without interfering with the mechanism. Verify the shaft’s actual rotation and the REST gap between positions 20 and 1.

## Phase 5 — Sensor prototype and diagnostics

The Pico bench test and integrated diagnostic program are complete. The integrated program samples raw angle, degrees, movement/stopped state, stable duration, magnet status, AGC, and magnitude while accepting Shelly activity/idle webhooks. OTA updates are implemented and tested so the mounted assembly can be updated without disturbing alignment.

## Phase 6 — Calibration and settle logic — provisional implementation

REST plus all 20 Mills positions are currently stored on the Pico. The Pico
uses movement, settling, calibrated windows, and duplicate suppression to
identify provisional slots. Weak-field behavior, outliers, REST-versus-20
separation, and final timing remain under validation.

## Phase 7 — Metadata integration — implemented for testing

Now-Playing's authenticated `/integrations/mills/selection` route maps slot N
to entry N in `Mills Playlist`. Live testing has shown correct metadata
selection. MPD play/pause behavior and complete Mills-session restoration
remain under refinement.

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

The Shelly webhook path, AS5600 bench test, installed provisional calibration,
and live slot-to-Now-Playing mapping are working. The next meaningful
milestone is improving the weak-field physical mount and validating complete
single- and multiple-record sessions, especially slot transitions and final
REST detection.

<!-- Last updated: 2026-09-16 -->
