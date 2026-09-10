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

Project kickoff. No production thresholds, calibration values, or control software have been selected yet. Initial work is observational and diagnostic.

## Related systems

- Now-Playing / moOde / MPD: orchestration and display integration
- Harmony Hub websocket: Denon source selection
- Denon AVR-4520CI: `Aux 1` for moOde, `Phono` for Mills
- Shelly 1PM Gen4 UL: Mills power switching and measurement
- Raspberry Pi Pico 2 W / Pico W: optional sensor gateway
