# Reference AS5600 Calibration

Reference snapshot captured from Pico `10.0.0.7` on 2026-09-16. These are the
currently accepted raw AS5600 positions for the installed magnet/sensor
geometry. The table is intentionally nonuniform; preserve the measured
relationships rather than assuming equal spacing.

| Point | Raw | Degrees | Spread | Magnitude |
| --- | ---: | ---: | ---: | ---: |
| REST | 2712 | 238.36 | 1 | 869 |
| 1 | 2965 | 260.60 | 1 | 704 |
| 2 | 3124 | 274.57 | 0 | 854 |
| 3 | 3247 | 285.38 | 1 | 810 |
| 4 | 3358 | 295.14 | 0 | 718 |
| 5 | 3432 | 301.64 | 1 | 596 |
| 6 | 3493 | 307.00 | 1 | 461 |
| 7 | 3567 | 313.51 | 0 | 326 |
| 8 | 3703 | 325.46 | 2 | 194 |
| 9 | 4057 | 356.57 | 4 | 84 |
| 10 | 1075 | 94.48 | 4 | 95 |
| 11 | 1372 | 120.59 | 1 | 235 |
| 12 | 1461 | 128.41 | 0 | 409 |
| 13 | 1561 | 137.20 | 1 | 576 |
| 14 | 1655 | 145.46 | 1 | 672 |
| 15 | 1752 | 153.98 | 1 | 291 |
| 16 | 1869 | 164.27 | 0 | 1385 |
| 17 | 2029 | 178.33 | 0 | 1194 |
| 18 | 2218 | 194.94 | 0 | 1386 |
| 19 | 2443 | 214.72 | 1 | 1150 |
| 20 | 2703 | 237.57 | 1 | 1145 |

## Relationship notes

Adjacent positions are measured rather than theoretical. The current
relationship sequence includes these notable intervals:

- REST → 1: 253 raw counts / 22.24°
- 8 → 9: 354 raw counts / 31.11°
- 9 → 10: 1114 raw counts / 97.91°
- 10 → 11: 297 raw counts / 26.10°
- 16 → 17: 160 raw counts / 14.06°
- 17 → 18: 189 raw counts / 16.61°
- 18 → 19: 225 raw counts / 19.78°
- 19 → 20: 260 raw counts / 22.85°
- 20 → REST: 9 raw counts / 0.79°

The 20-to-REST separation is currently inside the Pico's ±24 raw-count
matching window. Treat REST versus slot 20 as unresolved for final session-end
detection until the physical setup or calibration is improved. The table is
still useful as the current slot-identification reference.

## Rebuilding from a new REST reading

`override-rest.py` and the Pico calibration page use the current saved table as
the baseline. They calculate each signed circular step from REST through slot
20, then cumulatively reconstruct the table from the new REST raw value. No
historical REST value or equal-spacing assumption is used.
