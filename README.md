# Mills Throne of Music Integration

Integration project for connecting a 1939 Mills Throne of Music jukebox to the existing Now-Playing / moOde system.

## Objective

Observe the original Mills mechanism and enhance the listening experience without controlling or replacing its mechanical intelligence. The integration will:

1. Detect when the Mills becomes active.
2. Preserve enough of the pre-Mills MPD session to restore it later.
3. Switch the Denon AVR-4520CI from moOde (`Aux 1`) to the Mills (`Phono`) through the existing Harmony Hub websocket.
4. Identify the physical record eventually, preferably from the Mills number-wheel shaft.
5. Play the corresponding entry from the dedicated 20-track Mills playlist in MPD so existing Now-Playing metadata, artwork, progress, and client behavior continue to work normally.
6. Keep MPD on the current Mills surrogate while the physical Mills proceeds through its session.
7. Detect sustained return to true idle.
8. Switch the Denon back to moOde and restore the pre-Mills MPD session.

The Mills remains authoritative for record selection, ordering, mechanical operation, and audible audio. Now-Playing is the orchestration and display layer; it follows the physical machine rather than attempting to control or predict it.

## Settled design philosophy

- Preserve the original Mills mechanism completely.
- Observe physical facts; never electronically choose records or reproduce the Mills queue.
- Use the AS5600 and Pico as the likely primary mechanism observer.
- Use the Shelly 1PM as independent power/activity evidence, telemetry, and a smart master switch.
- Keep MPD, Harmony/Denon, metadata, and UI orchestration in Now-Playing.
- Treat a departure from REST through the final return to REST as one Mills session, even when multiple records play.
- Prefer local-LAN protocols and reversible, independently testable layers.

## Core design rules

- Observe; do not control the Mills mechanism.
- Do not reproduce the Mills queue or selection logic in software.
- Prefer non-contact sensing and local-LAN communication.
- Keep Shelly focused on power measurement, simple events, and independent confirmation.
- Let the Pico report selector-shaft observations; let Now-Playing decide what to do with them.
- Keep MPD, Harmony, metadata, and UI orchestration in Now-Playing.
- Build and verify each layer independently before combining them.
- Make integration endpoints idempotent so duplicate events are safe.

## Intended signal flow

```text
Mills selector shaft → magnet → AS5600 → Pico 2 W → Now-Playing
Mills power/current ───────────────────────────────→ supporting evidence
```

The Pico should report a calibrated slot only after the wheel has moved/searching has been observed and then settles. The REST gap between positions 20 and 1 is distinct from physical slot 20; angle 20 must be interpreted in movement/phase context.

When a physical selection is identified, Now-Playing may play the corresponding digital Mills playlist entry in MPD as a display surrogate. The Denon is switched to Phono, so the physical Mills remains the sound source while MPD supplies metadata, artwork, and progress to the displays.

## Source-switching and selection bridge

The initial integrated test was limited to Denon source switching. The current bridge also reports newly settled calibrated slots:

```text
Shelly activity threshold
  → POST /integrations/mills/stack-moving on Pico
  → Pico accepts the inactive → active transition once
  → POST /integrations/mills/start to Now-Playing
  → Harmony: Denon Aux 1 → Phono

Shelly sustained idle threshold
  → POST /integrations/mills/idle on Pico
  → Pico accepts the active → idle transition once
  → POST /integrations/mills/stop to Now-Playing
  → Harmony: Denon Phono → Aux 1
```

After AS5600 movement and settling, the Pico sends:

```text
Pico calibrated slot N
  → POST /integrations/mills/selection {"slot": N}
  → Now-Playing entry N in Mills Playlist
```

The Pico forwards only state transitions, not every repeated Shelly action. If Now-Playing or Harmony is unavailable, the Pico keeps the transition pending and returns an error so repeated Shelly delivery can retry. A mechanism power drop to the approximately 70 W record-playing level is not a session end; STOP is reserved for confirmed return to the true idle range.

Now-Playing routes require the configured `TRACK_KEY` in the Pico's `X-Track-Key` header. The current Pico configuration uses:

```python
NOW_PLAYING_URL = "http://10.0.0.4:3101"
```

The Pico now performs provisional AS5600 slot identification and sends settled selections. Now-Playing accepts `POST /integrations/mills/selection`, maps slot `N` directly to entry `N` in `Mills Playlist`, and has shown the correct metadata in live testing. MPD Mills-surrogate playback and pre-Mills MPD snapshot/restore remain under refinement; the current test may leave MPD paused while the physical Mills supplies the audible audio.

## MPD surrogate playback

At the beginning of a Mills session, Now-Playing takes one snapshot of the user's existing MPD session. The snapshot must ultimately preserve enough information to restore the prior listening experience, including as applicable:

- whether MPD was playing or paused
- the existing queue/playlist
- the current track
- the current playback position
- any other state required by the final restore implementation

The exact snapshot and restore mechanism remains **TBD** until we determine the safest way to preserve and reinstate the existing MPD queue and playback position. The integration must not destructively lose the user's queue while starting Mills surrogate playback.

After the Pico reports a settled physical selection, Now-Playing maps the physical slot to the corresponding entry in the dedicated 20-track Mills playlist and plays that digital entry in MPD. This allows normal Now-Playing metadata, artwork, progress, and client behavior to operate. MPD audio is not heard because the Denon is on `Phono`; the physical Mills record remains the actual audio source.

The pre-Mills MPD state is not restored between records. All physical records from the first departure from REST through the final return to REST belong to one Mills session, and the digital surrogate may change from one Mills selection to the next.

At confirmed session end, Now-Playing switches the Denon back to `Aux 1` and then restores the saved pre-Mills MPD state. Restoration occurs only after the final REST/session-end confirmation, not merely when one record rejects or the selector passes through position 20.

## Documentation

- [Architecture and state model](docs/architecture.md)
- [Hardware and sensing plan](docs/hardware-and-sensing.md)
- [Phased development plan](docs/development-plan.md)

## Status

Shelly activity webhooks, AS5600 bench testing, integrated Pico diagnostics, authenticated OTA updates, provisional REST/1–20 calibration, and settled-slot reporting are working. Live testing has confirmed that the detected physical slot can select the corresponding `Mills Playlist` entry in Now-Playing. The current Shelly thresholds are approximately `>55 W` for activity and `<50 W` for idle, with Pico-side idle debounce. The magnetic field remains flagged weak, and multi-record sequencing, tolerance windows, final REST confirmation, and MPD state restoration remain experimental.

## Pico software and OTA updates

The Pico program is in [`micropicoMills/main.py`](micropicoMills/main.py). The current program includes the Shelly activity webhooks, AS5600 diagnostic sampling, manual calibration capture, and provisional settled-slot reporting.

The Pico status page provides a calibrated-position hint. Once the wheel is settled, it compares the current angle with the saved points and shows `REST`, `slot N`, or `no calibrated match`. During an active Mills session, a newly settled slot 1–20 is also sent to Now-Playing as `POST /integrations/mills/selection`; this remains provisional while the weak-field sensor mounting is being evaluated.

### Provisional calibration

After the sensor and magnet are rigidly mounted, open the Pico calibration page:

```text
http://<pico-ip>/calibrate
```

Capture the current mechanical gap as `REST`, then capture slots 1–20 while each physical selector position is stopped. Each capture samples the AS5600 for about 1.1 seconds and saves the median raw angle, observed sample spread, magnetic status, AGC, and magnitude to the Pico-local `mills_calibration.json` file. `REST` is intentionally separate from slot 20.

The calibration page's REST override changes only the REST point and leaves slots 1–20 unchanged. This is the safe choice when the physical mount or magnet geometry has changed. The Mac-side [`override-rest.py`](override-rest.py) script provides the same behavior with a preview by default:

```bash
./override-rest.py 295
./override-rest.py 295 --apply
```

If the sensor/magnet assembly was only rotated as a rigid unit without changing centering, tilt, or air gap, the script can preview a full-table circular rebase. This is deliberately explicit because it is unsafe for a changed geometry:

```bash
./override-rest.py 295 --rebuild-from-relationships
./override-rest.py 295 --rebuild-from-relationships --apply
```

The full-table mode calculates its offset from the Pico's current saved REST value; it does not use a hard-coded historical REST value. For changed geometry, override or recapture individual rows instead.

Weak magnet readings are allowed but are recorded as provisional. The current installed calibration contains REST and slots 1–20; individual captures generally have 0–2 raw-count inlier spread, but the AS5600 continues to report `weak=YES` and occasional outliers. Improve the magnet alignment/air gap and repeat calibration before treating the values as production-quality. The Pico uses the saved points for provisional settled-slot reporting, and live testing has confirmed correct slot-to-playlist metadata mapping.

The Pico supports authenticated local-LAN OTA updates at:

```text
POST http://<pico-ip>/ota
Authorization: Bearer <OTA_TOKEN>
```

Before using OTA, add the same private token to the ignored local `micropicoMills/secrets.py` and to the Pico's `secrets.py`:

```python
OTA_TOKEN = "use-a-long-random-local-token"
```

Deploy the current program from the Mac with:

```bash
./deploy-pico.sh
```

The script defaults to Pico `10.0.0.7`. Override it with `PICO_IP=... ./deploy-pico.sh`, or provide a different source file as the first argument. It stages the upload as `main.new.py`, validates Python syntax, preserves the previous program as `main.backup.py`, installs the new `main.py`, reboots, and confirms the Pico responds afterward. The script reads `OTA_TOKEN` from the local ignored `micropicoMills/secrets.py`; alternatively set `MILLS_OTA_TOKEN` in the environment.

### OTA recovery

An interrupted upload or syntax-invalid file leaves the existing `main.py` untouched. If installation succeeds but the new program fails during boot, connect by USB/serial and rename the preserved backup:

```text
main.py       → main.failed.py   (optional)
main.backup.py → main.py
```

Then reboot the Pico. The backup is the last program that was running before the OTA replacement. Keep the Pico accessible by USB until OTA has been tested successfully.

## Related systems

- Now-Playing / moOde / MPD: orchestration and display integration
- Harmony Hub websocket: Denon source selection
- Denon AVR-4520CI: `Aux 1` for moOde, `Phono` for Mills
- Shelly 1PM Gen4 UL: Mills power switching and measurement
- Raspberry Pi Pico 2 W / Pico W: optional sensor gateway
