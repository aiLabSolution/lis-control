# Runbook — Lifotronic H9 passive RS-232 evidence capture (LIS-229)

This is the physical evidence gate for the Lifotronic H9 integration. The Manual-A0
baseline says the H9 uploads a proprietary serial stream at **115200 8N1**, with no
flow control, in `STX`…`S`/`Q`/`C`…`ETX` frames. This run must confirm that baseline
against the actual unit before any synthetic fixture graduates.

> **Prep artifact, not completed conformance.** The capture utility and this procedure
> can land before the analyzer is available. Model, firmware, host mode, connector,
> pinout, cable topology, and real bytes remain blank until the physical bench run.

The capture host is a passive observer. `scripts/h9_capture.py` opens the serial device
read-only and has no ACK, response, or order-download path. Physical wiring must also
be receive-only: connect the capture adapter's **RX and signal ground only**. Do not
connect its TX conductor to the analyzer.

## References and evidence form

- Capture tool: `scripts/h9_capture.py`; network-free tests:
  `scripts/test_h9_capture.py`.
- Evidence form and hardware inventory:
  `docs/testing/lifotronic-h9-bench-evidence-template.md`.
- Code-only S1 finding:
  `docs/testing/lifotronic-h9-pinned-baseline-audit.md`.
- Archive primitive: ADR-0012. Captures are stored as immutable
  `<sha256>.msg` + `<sha256>.json` entries, sharded by digest prefix.
- Scope and acceptance criteria: Plane LIS-229 and parent epic LIS-228.
- Protocol authority: private `manuals-and-lis-protocol` repository,
  `docs/LIFOTRONIC-H9-LIS-DRIVER-KNOWLEDGEBASE.md` (baseline SHA-256
  `0117c9733b275db754ff0759ba4ecc92151063e3b1f3fa14379dc77a5d3c7f0e`). This
  runbook does not replace it.

Use bench-only identifiers. Raw frames can contain specimen identifiers and must live
in the controlled evidence store, not in the git repository or tracker comments.

## Roles

| Role | Responsibility |
|---|---|
| Bench operator | Analyzer UI, bench-only sample/QC/calibration handling, photos, firmware and host-mode inventory. |
| Edge engineer | Passive breakout wiring, serial adapter, capture utility, digest verification, evidence extraction. |
| Validation owner | Safety approval, pass/deviation decision, evidence review, sign-off. |

## Equipment and prerequisites

- Physical Lifotronic H9 and access to its nameplate, system-information screen, and
  LIS/host configuration screen.
- Linux capture host with Python 3 and this repository revision.
- A named USB-to-RS-232 adapter; record manufacturer, model, serial, chipset, and its
  stable `/dev/serial/by-id/...` path.
- DB-9 breakout box or individually jumpered passive adapter, multimeter, and preferably
  an oscilloscope/logic analyzer rated for RS-232 levels.
- Straight-through and null-modem/crossover options, with connector genders recorded.
- A lead that exposes only adapter RX and signal ground to the analyzer. Hardware
  handshaking conductors must remain disconnected.
- Approved bench-only patient, QC, and calibration material as applicable.

Create one controlled run directory outside the repository (replace the placeholder
with the site's approved evidence-store mount):

```text
/path/to/controlled-evidence/lifotronic-h9/<YYYYMMDD>-<device-serial>/
```

Copy the evidence template there as `identity-and-inventory.md` and fill it during the
run. Do not pre-fill an unobserved value as “confirmed”.

## 1. Inventory the physical unit before wiring

1. Photograph the nameplate and record model, device serial, hardware revision, and
   manufacture/service identifiers.
2. Photograph the system-information and LIS/host screens. Record firmware/software
   revision, protocol/manual revision shown by the unit, selected host mode, and whether
   the interface is described as serial, RS-232, LIS, or another site-specific variant.
3. Record the analyzer DB-9 connector gender and its labels. Do not infer DTE/DCE role
   from gender alone.
4. Record every adapter/cable/null-modem/breakout component end-to-end.

Pass: the inventory table and photos identify the exact unit and its current firmware.
The firmware/Manual-A0 AC remains open until these observations are complete.

## 2. Determine the receive-only wiring

For a conventional PC/DTE DB-9, pin 2 is RXD, pin 3 is TXD, and pin 5 is signal ground.
That is a reference for the **capture adapter**, not an assertion about the H9 port.

1. With a breakout or scope, determine which H9 pin transmits during a manual upload.
   Record the idle and active levels and the analyzer-side signal ground.
2. Connect H9 signal ground to capture-adapter signal ground.
3. Route the observed H9 TX signal to the capture adapter's RX input:

   | Observed H9 transmit pin | Candidate receive topology | Bench disposition |
   |---|---|---|
   | DB-9 pin 2 | Straight-through signal path to adapter pin 2 | Confirm with bytes; record connector genders. |
   | DB-9 pin 3 | Crossover/null-modem signal path to adapter pin 2 | Confirm with bytes; record connector genders. |
   | Other | Vendor/site variant | Stop and document the measured pinout before proceeding. |

4. Leave capture-adapter TX (normally DB-9 pin 3), RTS, CTS, DTR, DSR, DCD, and RI
   disconnected. Verify continuity before attaching the analyzer.
5. Photograph the breakout and record the confirmed H9 pin-to-adapter pin map in the
   evidence form.

Pass: analyzer TX and ground are identified from measurement, the capture host has no
conductive transmit path back to the H9, and straight-versus-null-modem usage is recorded.

## 3. Prepare the capture host

Identify the stable port and confirm permissions:

```bash
ls -l /dev/serial/by-id/
python3 scripts/h9_capture.py --help
python3 -m unittest scripts/test_h9_capture.py -v
```

The tool configures **115200 baud, 8 data bits, no parity, 1 stop bit, no software or
hardware flow control**. It uses `O_RDONLY | O_NOCTTY | O_NONBLOCK`; it does not call
`write(2)`, assert an application ACK, or issue an order command. The RX+ground-only
wiring in Step 2 is the hardware safety boundary even if an adapter driver manipulates
modem-control lines when opened.

## 4. Capture a real upload

Start the tool before asking the analyzer to upload. Quote inventory strings that
contain spaces:

```bash
python3 scripts/h9_capture.py \
  --port /dev/serial/by-id/<adapter-id> \
  --outdir /path/to/controlled-evidence/lifotronic-h9/<run>/archive \
  --frames 1 \
  --model "Lifotronic H9" \
  --serial-number "<device-serial>" \
  --firmware "<observed-firmware>" \
  --host-mode "<observed-host-mode>" \
  --connector "<observed-gender-and-pinout>" \
  --cable "<adapter/cable/null-modem inventory>" \
  --operator "<operator>"
```

Trigger one patient-measurement upload using a bench-only Sample SN. With `--frames 1`,
the tool waits for a structurally valid frame and then for one second of serial-line
quiet before finalizing; this settle window prevents a valid-length in-frame ETX prefix
from cutting off a later tail. Use `--settle <seconds>` only when bench evidence justifies
a different quiet window. Omit `--frames` to capture until Ctrl-C. Run separate, labeled
captures for QC (`Q`) and calibration (`C`) only if the validation owner approves those
analyzer operations.

Manual-A0 structural hypotheses reported in the sidecar are:

| Block | Application length, excluding STX/ETX | Interpretation for capture labeling |
|---|---:|---|
| `S` | `120 + 6N` | Measurement with zero or more six-byte chromatogram points. |
| `Q` | `109` | QC summary. |
| `C` | `64` | Calibration summary. |

The analyzer may put byte values `0x02` or `0x03` inside an application body. The
readability analysis prefers a terminator that satisfies the structural length, while
the `.msg` archive always retains the entire raw stream, including noise, malformed
data, and truncated tails.

Pass: the command prints a non-empty raw archive path, JSON sidecar path, SHA-256, and
at least one frame summary. An unfamiliar or length-invalid frame is a captured
deviation, not permission to edit or discard bytes.

## 5. Verify the archive and replay

The output layout is `<outdir>/<digest-prefix>/<digest>.msg` beside `<digest>.json`.
Verify the raw file independently and compare the value to the JSON `digest` field:

```bash
sha256sum /path/to/controlled-evidence/lifotronic-h9/<run>/archive/<prefix>/<digest>.msg
python3 scripts/h9_capture.py \
  --replay /path/to/controlled-evidence/lifotronic-h9/<run>/archive/<prefix>/<digest>.msg
```

Confirm in the sidecar:

- `byte_count` matches the raw file;
- `read_events` records UTC receive time, offset, and byte count for each read;
- serial settings say 115200 8N1, no flow control, `open_mode=read-only`;
- model, serial, firmware, host mode, connector, and cable values match the evidence
  form;
- frame offsets and per-frame digests describe the raw archive without embedding the
  specimen payload in metadata.

Identical byte streams resolve to the same immutable archive entry. Do not edit a `.msg`
or `.json` in place; create a new capture if metadata or bytes are wrong. Replay and
re-archival reject a missing, malformed, or raw-inconsistent sidecar. The live CLI also
rejects output paths inside this repository checkout.

## 6. Close the evidence packet

Collect at minimum:

| Artifact | Required content |
|---|---|
| `identity-and-inventory.md` | Completed evidence template and AC disposition. |
| `nameplate.jpg` | Model, serial, hardware revision. |
| `system-info.png` | Firmware/software revision. |
| `host-settings.png` | Host mode and 115200 8N1/no-flow-control configuration. |
| `wiring.jpg` | DB-9 genders, breakout, analyzer TX→adapter RX, and ground. |
| `<digest>.msg` | Exact raw serial stream. |
| `<digest>.json` | SHA-256 sidecar, timestamps, inventory, serial settings, frame map. |
| `replay.txt` | Offline replay output and independent `sha256sum`. |
| `signed-conformance-report.pdf` | Validation-owner decision. |

Post only artifact identifiers and digests to Plane/PR comments. Keep raw evidence and
photos in the controlled evidence store.

## Troubleshooting and stop conditions

- **No bytes:** confirm the analyzer actually uploaded, adapter permissions, stable
  device path, common signal ground, and analyzer TX pin. Swap straight/crossover
  topology only at the breakout while keeping adapter TX disconnected.
- **Garbled bytes:** record the raw stream first, then re-check baud/data/parity/stop and
  ground. Do not “clean” the archived bytes.
- **Bytes but no valid frame:** retain the capture and record firmware/host-mode deviation.
  A different framing/protocol is a separately gated site variant.
- **Analyzer expects a response:** stop. This tool must remain passive; an ACK or
  bidirectional protocol would contradict the upload-only baseline and needs a new
  reviewed design, not a bench improvisation.
- **Real patient identifiers appear:** stop sharing the packet, move it to the approved
  protected store, and follow the site's privacy incident procedure if exposure occurred.

## Exit criteria / LIS-229 acceptance criteria

- A real H9 stream is archived as exact bytes with a matching SHA-256 sidecar.
- DB-9 pinout, connector genders, straight/null-modem topology, and 115200 8N1 with no
  flow control are confirmed on the physical unit.
- The pinned-code drift item is evidenced by
  `docs/testing/lifotronic-h9-pinned-baseline-audit.md`.
- Firmware and host mode are confirmed as Manual-A0 proprietary RS-232, or the observed
  variant is documented and separately gated.
- The validation owner signs the packet.

Until the physical artifacts and sign-off exist, LIS-229 remains open even though the
capture tooling and code-only drift audit have landed.
