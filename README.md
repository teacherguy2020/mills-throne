# Mills Throne of Music Integration

Integration project for connecting a 1939 Mills Throne of Music jukebox to the existing Now-Playing / moOde system.

## Objective

Observe the original Mills mechanism and enhance the listening experience without controlling or replacing its mechanical intelligence. The integration will:

1. Detect when the Mills becomes active.
2. Pause MPD only when it was playing before the Mills started.
3. Switch the Denon AVR-4520CI from moOde (`Aux 1`) to the Mills (`Phono`) through the existing Harmony Hub websocket.
4. Identify the physical record eventually, preferably from the Mills number-wheel shaft.
5. Display matching Now-Playing metadata and artwork for clients and TVs.
6. Detect sustained return to true idle.
7. Switch the Denon back to moOde and resume MPD only when this integration paused it.

The Mills remains the authoritative audio source and selector. Now-Playing is the orchestration and display layer.

## Core design rules

- Observe; do not control the Mills mechanism.
- Do not reproduce the Mills queue or selection logic in software.
- Prefer non-contact sensing and local-LAN communication.
- Keep Shelly focused on power measurement and simple events.
- Keep MPD, Harmony, metadata, and UI orchestration in Now-Playing.
- Build and verify each layer independently before combining them.
- Make integration endpoints idempotent so duplicate events are safe.

## Documentation

- [Architecture and state model](docs/architecture.md)
- [Hardware and sensing plan](docs/hardware-and-sensing.md)
- [Phased development plan](docs/development-plan.md)

## Status

Shelly activity webhooks, AS5600 bench testing, integrated Pico diagnostics, and authenticated OTA updates are working. The AS5600 has not yet been mounted or calibrated on the Mills. Production thresholds, calibrated angles, tolerance windows, timing, and final Pico-to-Now-Playing event rules remain to be determined experimentally.

## Pico software and OTA updates

The Pico program is in [`micropicoMills/main.py`](micropicoMills/main.py). The current program includes the Shelly activity webhooks and AS5600 diagnostic sampling, but does not yet identify calibrated record slots.

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
