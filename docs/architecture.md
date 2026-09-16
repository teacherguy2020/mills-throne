# Architecture and State Model

## Responsibility boundaries

| Component | Responsibility | Must not do |
| --- | --- | --- |
| Mills jukebox | Select, load, play, reject, and queue records mechanically | Accept electronic selection/control from the integration |
| Shelly 1PM Gen4 UL | Master power, power/current measurement, activity/idle confirmation, local event delivery | MPD or Harmony orchestration |
| Pico 2 W / Pico W | Observe selector-shaft angle, movement, REST/search/settle context, and eventual slot number | Choose records or infer the Mills queue |
| Now-Playing | Own integration state, MPD, Harmony, record mapping, metadata, and UI; manage Mills surrogate playback and session restoration | Override Mills mechanical behavior |
| Denon AVR-4520CI | Select the physical audio source | — |

## Conceptual lifecycle

```text
REST / IDLE
  └─ selector leaves REST and genuine search begins
       ├─ Pico reports Mills ACTIVE
       ├─ Now-Playing snapshots enough pre-Mills MPD state to restore later
       ├─ pauses MPD if necessary
       ├─ selects Denon Phono through Harmony
       └─ MILLS_ACTIVE

MILLS_ACTIVE
  ├─ remain active across searches and multiple selections
  ├─ accept settled record observations
  ├─ play each mapped selection from the dedicated 20-track Mills playlist in MPD
  ├─ leave the pre-Mills MPD state untouched until the session ends
  └─ selector returns to REST and remains stable
       └─ Shelly idle level may provide independent confirmation
       ├─ select Denon Aux 1 through Harmony
       ├─ restore the saved pre-Mills MPD state
       └─ IDLE
```

The start and stop handlers must be idempotent. A repeated start while active must not pause an already-paused MPD session or overwrite the original resume decision. A repeated stop while idle must not resume MPD.

### Short-term source-switching milestone

The initial integration milestone uses the Pico as the Shelly event gateway:

```text
Shelly start → Pico active latch → Now-Playing START → Harmony → Denon Phono
Shelly idle  → Pico idle latch   → Now-Playing STOP  → Harmony → Denon Aux 1
```

The Pico forwards only inactive→active and active→idle transitions. During an active session, it also reports a newly settled calibrated slot after selector-shaft movement. Now-Playing serializes and idempotently handles its own transitions. The event called `idle` means the whole Mills session has returned to true idle, not merely that the record stack motor stopped; the approximately 70 W record-playing state remains active.

The Mills session remains active across record rejection, reset toward #20, and subsequent searches. A wheel reading of 20 is not sufficient by itself: 20 is a numbered position during search, while the gap between 20 and 1 is the true REST position.

## Proposed event endpoints

```text
POST /integrations/mills/start
POST /integrations/mills/stop
POST /integrations/mills/selection
```

Selection payload:

```json
{
  "slot": 7
}
```

The selection event is emitted only after the number wheel has moved, stopped, and matched a calibrated slot window for the configured settle interval. REST is never emitted as a selection, and the Pico suppresses duplicates until new movement occurs. It must not report every number passed during a search.

## MPD surrogate and restoration invariant

At the first accepted start transition, snapshot enough of the existing MPD session to restore the user's prior listening experience. This includes the queue/playlist, current track, playback position, and playing/paused state as required by the eventual implementation. The exact snapshot/restore mechanism is **TBD** pending a safe way to preserve and reinstate the queue and position without destructive MPD changes.

If MPD was playing when the Mills session began, pause it before switching the Denon to `Phono`; if it was already paused or stopped, do not invent a resume action later. The original state snapshot must not be overwritten by later Mills selections.

When the Pico reports a settled physical selection, Now-Playing maps its slot to the same-position entry in the dedicated 20-track Mills playlist and plays that entry in MPD. This is intentional surrogate playback: MPD provides normal metadata, artwork, progress, and client behavior, while the Denon being on `Phono` means listeners hear the physical Mills record instead of MPD.

Do not restore the pre-Mills MPD state between records. A Mills session spans all selections from the initial departure from REST through the final return to REST, and each new settled selection replaces the current digital surrogate as needed.

Only after confirmed final REST/session end does Now-Playing switch the Denon back to `Aux 1` and restore the saved pre-Mills MPD state. A record rejection, reset toward #20, or intermediate search must not trigger restoration.

## Record mapping

The eventual Mills catalog maps a physical slot to the digital counterpart:

```text
physical slot → artist, title, album, library path/track/MBID, artwork
```

The physical record remains the audio source; the digital library supplies display metadata and artwork only.

Current Pico commissioning and reporting endpoints are local-LAN receivers:

```text
POST http://10.0.0.7/integrations/mills/stack-moving
POST http://10.0.0.7/integrations/mills/idle
GET  http://10.0.0.7/status
GET  http://10.0.0.7/calibration
GET  http://10.0.0.7/calibrate
```

The Pico also sends authenticated selection events to Now-Playing:

```text
POST http://10.0.0.4:3101/integrations/mills/selection
X-Track-Key: <TRACK_KEY>
{"slot": 1..20}
```

This is currently provisional and is validated against the installed calibration table and real Mills cycles.

The temporary Now-Playing source-switching endpoints are:

```text
POST /integrations/mills/start  # authenticated; switch Denon to Phono
POST /integrations/mills/stop   # authenticated; switch Denon to Aux 1
GET  /integrations/mills/status # authenticated diagnostic state
```

They use the existing `TRACK_KEY` request authentication and the proven
Harmony Hub WebSocket protocol. Harmony host, hub, and Denon device settings
are supplied through the Now-Playing service environment; they are not stored
in this repository.

<!-- Last updated: 2026-09-16 -->
