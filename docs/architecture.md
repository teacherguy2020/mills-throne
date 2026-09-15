# Architecture and State Model

## Responsibility boundaries

| Component | Responsibility | Must not do |
| --- | --- | --- |
| Mills jukebox | Select, load, play, reject, and queue records mechanically | Accept electronic selection/control from the integration |
| Shelly 1PM Gen4 UL | Master power, power/current measurement, activity/idle confirmation, local event delivery | MPD or Harmony orchestration |
| Pico 2 W / Pico W | Observe selector-shaft angle, movement, REST/search/settle context, and eventual slot number | Choose records or infer the Mills queue |
| Now-Playing | Own integration state, MPD, Harmony, record mapping, metadata, and UI | Override Mills mechanical behavior |
| Denon AVR-4520CI | Select the physical audio source | — |

## Conceptual lifecycle

```text
REST / IDLE
  └─ selector leaves REST and genuine search begins
       ├─ Pico reports Mills ACTIVE
       ├─ Now-Playing remembers whether MPD is playing
       ├─ pauses MPD if necessary
       ├─ selects Denon Phono through Harmony
       └─ MILLS_ACTIVE

MILLS_ACTIVE
  ├─ remain active across searches and multiple selections
  ├─ accept settled record observations
  └─ selector returns to REST and remains stable
       └─ Shelly idle level may provide independent confirmation
       ├─ select Denon Aux 1 through Harmony
       ├─ resume MPD only if this integration paused it
       └─ IDLE
```

The start and stop handlers must be idempotent. A repeated start while active must not pause an already-paused MPD session or overwrite the original resume decision. A repeated stop while idle must not resume MPD.

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

The selection event should be emitted only after the number wheel has stopped and remained within a calibrated slot window for the configured settle interval. It must not report every number passed during a search.

## MPD resume invariant

At the first accepted start transition, record whether MPD was actually playing. Pause only in that case. On the accepted stop transition, resume only when the integration recorded that it paused MPD. Never resume MPD solely because a stop event arrived.

## Record mapping

The eventual Mills catalog maps a physical slot to the digital counterpart:

```text
physical slot → artist, title, album, library path/track/MBID, artwork
```

The physical record remains the audio source; the digital library supplies display metadata and artwork only.

Current Pico commissioning endpoints are local-LAN webhook receivers:

```text
POST http://10.0.0.7/integrations/mills/stack-moving
POST http://10.0.0.7/integrations/mills/idle
GET  http://10.0.0.7/status
```

These are diagnostic/activity endpoints and are not yet the final Pico-to-Now-Playing protocol.

<!-- Last updated: 2026-09-15 -->
