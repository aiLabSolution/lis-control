# Lifotronic H9 bench evidence and hardware inventory template (LIS-229)

Copy this file into the controlled bench evidence directory as
`identity-and-inventory.md`. Fill values from the physical unit and raw capture; do not
commit raw analyzer data or patient identifiers to this repository.

## Run identity

| Item | Observed value / artifact |
|---|---|
| Bench date/time and timezone | |
| Site / bench identifier | |
| Bench operator | |
| Edge engineer | |
| Validation owner | |
| Repository commit | |
| `scripts/h9_capture.py` SHA-256 | |
| Evidence directory | |

## Analyzer inventory

| Item | Observed value / artifact |
|---|---|
| Manufacturer | Lifotronic (confirm) |
| Model | H9 (confirm) |
| Device serial number | |
| Hardware revision | |
| Firmware/software revision | |
| Manufacture/service date | |
| Protocol/manual revision shown or supplied | |
| Host/LIS mode name | |
| Upload-only behavior observed | yes / no / deviation |
| Nameplate photo | |
| System-information screenshot | |
| Host-settings screenshot | |

## Serial port and cable inventory

| Item | Observed value / artifact |
|---|---|
| Analyzer connector type and gender | |
| Capture-adapter connector type and gender | |
| Analyzer TX pin (measured) | |
| Analyzer signal-ground pin (measured) | |
| Capture-adapter RX pin | |
| Capture-adapter signal-ground pin | |
| Straight-through / null-modem / custom breakout | |
| Capture-adapter TX physically disconnected | yes / no |
| RTS/CTS/DTR/DSR/DCD/RI disconnected | yes / no |
| Cable manufacturer / part / asset ID | |
| Null-modem or breakout manufacturer / part / asset ID | |
| USB-RS232 adapter manufacturer / model / serial / chipset | |
| Stable device path (`/dev/serial/by-id/...`) | |
| Wiring photo | |

### Measured analyzer DB-9 pinout

Record measured or vendor-confirmed function; use `NC/unknown` rather than guessing.

| Pin | Function | Direction relative to H9 | Evidence / measurement |
|---:|---|---|---|
| 1 | | | |
| 2 | | | |
| 3 | | | |
| 4 | | | |
| 5 | | | |
| 6 | | | |
| 7 | | | |
| 8 | | | |
| 9 | | | |

### Serial settings confirmation

| Setting | Manual-A0 baseline | Observed |
|---|---:|---|
| Baud | 115200 | |
| Data bits | 8 | |
| Parity | none | |
| Stop bits | 1 | |
| Software flow control | none | |
| Hardware flow control | none | |

## Capture inventory

| Capture | Required | Raw file | SHA-256 / sidecar | Frame finding / notes |
|---|---:|---|---|---|
| Patient measurement (`S`) | yes | | | |
| QC (`Q`) | if approved/available | | | |
| Calibration (`C`) | if approved/available | | | |
| Malformed/noise characterization | if observed | | | |

For each sidecar confirm:

- [ ] digest equals independent `sha256sum` of the `.msg` file;
- [ ] `byte_count` equals file size;
- [ ] `read_events` contain UTC timestamps and contiguous offsets;
- [ ] serial settings are 115200 8N1, no flow control, read-only;
- [ ] analyzer, firmware, host mode, connector, and cable metadata match this form;
- [ ] frame offsets/digests refer to the raw stream and contain no copied specimen text;
- [ ] offline `--replay` reports the same stream and frame digest(s).

## Protocol observations

| Question | Observation / evidence |
|---|---|
| First application byte(s) observed (`S`, `Q`, `C`, other) | |
| Measurement length matches `120 + 6N` | |
| QC summary length matches 109 | |
| Calibration summary length matches 64 | |
| Leading/trailing noise or truncated data | |
| In-frame `0x02` / `0x03` observed | |
| Analyzer required any host response | |
| Manual-A0 proprietary RS-232 baseline confirmed | yes / no / deviation |
| Separately gated site/firmware variant needed | |

## LIS-229 acceptance-criteria disposition

| Acceptance criterion | MET / BLOCKED / DEVIATION | Evidence |
|---|---|---|
| Real H9 capture archived with SHA-256 + sidecar | | |
| DB-9 pinout and 115200 8N1/no-flow-control confirmed | | |
| Pinned-code drift state documented | MET (pre-bench) | `docs/testing/lifotronic-h9-pinned-baseline-audit.md` |
| Firmware/host mode confirmed as Manual-A0 proprietary RS-232 or variant recorded | | |

## Deviations, actions, and sign-off

| Deviation / risk | Owner | Follow-up issue | Disposition |
|---|---|---|---|
| | | | |

Validation decision: PASS / CONDITIONAL / FAIL

Validation owner: ____________________  Date: ____________________

Edge engineer: _______________________  Date: ____________________

Bench operator: ______________________  Date: ____________________
