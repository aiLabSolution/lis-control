# Context — Edge / drivers (analyzer-bridge)

> Layered context for the `edge/drivers` submodule. Hosted in the umbrella alongside the
> pin. The edge engine is the reused **`openelis-analyzer-bridge`**, settled as the production
> edge substrate by **ADR-0015** (LIS-12). Vested as a submodule by LIS-90.

## What this is

The **interface engine** — the edge layer that ingests analyzer messages (HL7 v2.x / ASTM /
serial / file), normalizes them, and forwards to the OpenELIS core. We adopt it by **reusing
`openelis-analyzer-bridge`** (MPL-2.0, OpenELIS-family; namespace `org.itech.ahb`) rather than
building bespoke drivers or adopting a separate integration engine (ADR-0008 / DEC-04; license
cleared under HOLD-001 / LIS-71).

## Repo & versioning

- **Mount:** `edge/drivers/` (git submodule, pinned in `lis-control`).
- **origin:** `https://github.com/aiLabSolution/openelis-analyzer-bridge.git` — standalone
  (not a GitHub fork); default & tracked branch `develop`.
- **Pin:** untagged **`963b39a`** — LIS-174 SNIBE MAGLUMI X3 native simplified-envelope
  ASTM receive path (PR `openelis-analyzer-bridge#21`): third framing profile
  `SnibeAstmCommunicator` (`AWAIT_ENQ → AWAIT_STX → RECORDS → AWAIT_EOT`; ACK at exactly
  ENQ/STX/ETX/EOT, never per record; no NAK vocabulary, no retransmit — any unexpected
  byte/timeout/EOF ⇒ log + close, the analyzer reconnects; ISO-8859-1 decode; SO_TIMEOUT
  parity knob `so-timeout-seconds`, idle keep-alive between envelopes ends cleanly;
  multi-envelope per connection; zero-record envelopes rejected before ETX-ACK), a
  `CommunicatorFactory` seam in `ASTMServlet` (default = byte-for-byte
  `GeneralASTMCommunicator` for the LIS01-A/E1381-95 listeners), an opt-in
  `org.itech.ahb.listen-astm-server.snibe` listener bean (port 12021, docker
  12020:12021, absent block ⇒ no bean, port never opened; `direction: upload-only` — the
  simplified-envelope send half is LIS-177) and the `Enable Checksum` mirror (design D4):
  `checksum: true` delegates the snibe port to the existing compliant E1381-95 path —
  the single swap point if the LIS-75 capture refutes the standard-E1381 hypothesis.
  Cross-language SHA-256 anchors pin the bridge tests to the `edge/sim` fixtures (drift
  breaks a test on either side). Landed with adversarial APPROVE + CLEAN fix-verify;
  full suite at this merged pin **777/0/0/5** (762/0/0/5 on the PR #21 branch pre-merge;
  bridge has no CI — local runs are the record). **Gap 4 of the LIS-119 era is hereby landed
  pending the LIS-75 bench proof** (AC-1 real-capture evidence; synthetic proof only
  until then); X3 codes/units stay synthetic until LIS-75/LIS-38. Sits on top of the
  intervening `b2678d9` (LIS-149 EDAN H90-series worklist ORF profile, PR #22) and
  `8d4f75a` (LIS-175 X3 analyzer channel registration, PR #20), both landed 2026-07-07
  by parallel sessions on `bd43706` below.
- **Prior pin:** untagged **`bd43706`** — LIS-149 AC1 closed-loop host-query test
  (PR `openelis-analyzer-bridge#19`, test-only, no production code changed):
  `HostQueryResultRoundTripTest` chains `Hl7HostQueryResponder`'s ORF^R04 answer
  into a follow-up ORU^R01 through `HL7ResultParser`, proving the accession a
  barcode host-query reconciles to is the same accession the analyzer's result
  attaches to (no orphan sample) — closing the gap the 2026-07-06 ac-verifier
  pass found on LIS-149 AC1. Sits on top of the intervening pin `f68c5e8`
  (LIS-125 ASTM/Snibe calibration gate, PR #18) and `ee3ec26` below.
- **Prior pin:** untagged **`ee3ec26`** — LIS-124 serial-HL7 ACK coupling
  (PR `openelis-analyzer-bridge#17`): the MLLP-over-RS232 HL7 *application* ACK now
  fires **after** routing and is outcome-dependent — `MSA|AA` on delivery success,
  `MSA|AE` NAK on routing failure / handler exception / ACK-budget timeout — mirroring
  the TCP MLLP path (previously it was always `AA`, emitted at frame time before
  routing, so failed/undeliverable results were silently lost). A new
  `SerialHl7AckBuilder` owns ACK/NAK construction (MSH swap-echo, MSA-2 = inbound
  MSH-10, lenient `BRIDGE`/`ANALYZER`/`UNKNOWN` fallback); `SerialFrameBuffer` is
  HL7-framing-only (`getCompletedMessages()` → `CompletedMessage(payload, protocol)`);
  the pre-ACK route is bounded by the new `org.itech.ahb.serial.hl7-ack-budget-ms`
  (default 10 000 ms, below the 15 s ASTM frame-ACK precedent), on timeout the route is
  not cancelled (OE upsert is idempotent). **ASTM link-layer ACK/NAK is byte-identical**
  (LIS-23/25, ADR-0009). Deferred: LIS-172 (head-of-line NAK amplification under
  sustained OE outage). Sits on top of the intervening pins `1ca2c74` (LIS-122
  analyzer/specimen identity + accession minting, PR #16), `371921c` (LIS-98 code↔LOINC
  sync, PR #15) and the LIS-149 host-query work — the detailed genealogy below is
  retained from the `aae56e8` (LIS-119) era.
- **Prior pin:** untagged **`aae56e8`** (`3.0.9-3-gaae56e8`) — the LIS-119 SnibeLis/MAGLUMI X3
  bridge adapter (PR `openelis-analyzer-bridge#12`: ASTM R.6 reference range →
  `Observation.referenceRange` (raw text always, guarded numeric low/high w/ UCUM),
  R.7 abnormal flag → `Observation.interpretation` (v3-coded N/L/H/LL/HH/A/AA/</>,
  unknown flags carried as text), tolerant R.13 completion-time read (pinned idx 9
  precedence → spec R.13 → 14-digit scan, recovering the SnibeLis manual's R.12
  off-by-one) + compact→ISO normalization so `Observation.effective` actually emits
  (pre-existing silent drop for all ASTM analyzers), `uIU/mL`/`pmol/L` UCUM backstop.
  Gap 4 — the X3's simplified ENQ/STX/…/ETX/EOT session framing — became its own slice,
  **LIS-174** (**landed** at the current pin, 2026-07-07; real-capture proof still
  pending the **LIS-75** bench capture of the X3's native `Online` ASTM output against
  **our bridge** — direct-attach; the SnibeLis middleware was dropped from the topology
  2026-07-06 — LIS-178 / ADR-0008+0015 amendments); X3 codes/units stay synthetic until
  LIS-75/LIS-38.
  Follows release `3.0.9` (`fb2167c`) — the LIS-88 bridge change (PR
  `openelis-analyzer-bridge#10`: FILE routed through the shared
  `MessageNormalizer`/`HttpForwardingRouter` pipeline via a `parsedResults` envelope
  field — parse stays in the FILE listener, send/retry/rejection-capture/metrics are
  the common path; inert `DeadLetterWriter` removed, SQLite `rejected_bundles`
  documented as the single rejection store of record; plus PR #11 adversarial-review
  follow-ups: listener-bound analyzer identity takes precedence over central source
  lookup, and a null forward-URI guard replaces an NPE) — and the untagged `f28923d`
  (LIS-109, PRs #8/#9: H99S blank-placeholder suppression) and `3.0.7` (`fe391a7`,
  LIS-28 / PR #6: registry-backed raw-unit→UCUM mapping — `AnalyzerEntry.unitToUcum`
  feeds FHIR `Quantity.system/code`, `testUnitUcum` wired through `/register` +
  `/sync`; OE-core does not *send* `testUnitUcum` yet — lands with the LIS-98 fix),
  which followed `3.0.6` (`c7382e4`, LIS-26: ERBA EC90 ASTM normalization —
  E1381-95 framed compliant receive, e1381-95 config-key fix, UCUM `Quantity`
  coding) on top of the EDAN H90-series parse profile (PR #4) and the LIS-95 SD1
  QC/calibration gate (PR #3).
  The `3.0.x` release line is pom-independent (pom stays `3.3.0`, no bump on tag).
- **Bump the pin (two-level):** PR the change on `openelis-analyzer-bridge` first, then
  `git -C <umbrella> add edge/drivers && git commit` to record the new pin in an umbrella PR
  (ADR-0001 / CLAUDE.md).
- **Stack:** Java (Spring Boot); HAPI HL7 v2 for MLLP, `astm-http-lib` for ASTM.

## Module boundaries (ADR-0015 §2 — transport-invariant seam)

```
analyzer ──▶ framer (transport-specific)           ──▶ MessageEnvelope (convergence seam)
             HapiMLLPListener / SerialFrameBuffer        │
             / ASTMServlet / FileWatcher                  ▼
                                            MessageNormalizer → HL7ResultParser / ASTMResultParser
                                            → FhirBundleBuilder (codeToLoinc)
                                            ──▶ FHIR R4 Bundle → POST /analyzer/fhir → OpenELIS core
```

- **Framer** = transport-specific (the only layer that knows the wire).
- **Parser** = protocol-specific, not transport-specific.
- **Normalization** = analyzer-code → LOINC/UCUM, carried on the **OpenELIS analyzer registry**
  entry (`AnalyzerEntry.codeToLoinc`); the bridge pulls `/rest/analyzer/analyzers` on startup.
  Adding/re-mapping an analyzer on an enabled transport is **config, not redeploy**.
- **Ingest contract** = a FHIR R4 transaction Bundle POSTed to `/analyzer/fhir` (ADR-0015 §5;
  the production serialization of core ADR-0003's `NormalizedObservation` DTO, which the Python
  `edge/sim` simulator speaks).

## Pilot substrate

MLLP/HL7 is the pilot transport and the only one that must be enabled + bench-proven for
go-live (EDAN H60S anchor, port 7999; bridge default 2575). Serial/ASTM (Stage 2) and the
MAGLUMI X3's native ASTM-over-TCP direct attach (Stage 3 — SnibeLis middleware dropped
2026-07-06, LIS-178 / ADR-0015 amendment; FILE demoted to the LIS-34 contingency) are the
recorded forward path — bench-validated against the simulators, post-pilot for the live
fleet under change control (DEC-06 / SD-0). DEC-06 released one narrow exception on
2026-07-04: LIS-149 may build and bench the EDAN H99S `QRY^R02 -> ORF^R04` worklist/order-download
path; support still requires signed H99S wire evidence. Enabling a transport is configuration plus
a restart; it ships no new code.

## Component decisions / references

- **ADR-0015** (umbrella) — edge transport substrate: direct attachment to the bridge's native
  listeners; channel-config schema; REQ-SEC-03 two-tier isolation; FHIR northbound.
- **ADR-0008** (umbrella) — interface engine = reuse the bridge; Java production stack; v1 fleet.
- **ADR-0005** (umbrella) — MLLP framing + ACK modes (original-mode for the v1 fleet).

## Open items / residuals (ADR-0015 §4, tracked as follow-ups)

- Intra-bridge isolation is thread-level (shared JVM); rate-limiting is MLLP-only; the
  source allow-list is advisory (TB-1 spoofing gap). Change-controlled hardening,
  L5-proven in Stage 5 — **LIS-91** (hardening) / **LIS-89** (threat-model wording).
- ~~FILE channel bypasses the shared normalizer~~ / ~~inert filesystem DLQ~~ — **closed**
  by LIS-88 / PRs #10+#11, release `3.0.9`: FILE accessions enter the `MessageEnvelope` seam
  (`parsedResults`) and route through the common pipeline; `DeadLetterWriter` removed,
  `rejected_bundles` is the DLQ of record (bridge README §Rejection handling). (The ASTM
  E1381-95 config-key mismatch, originally here, was **closed** by LIS-26 / PR #5, release
  `3.0.6`: the key now binds under `listen-astm-server.e1381-95` and `E1381_95` uses the
  framed compliant receive path.)
- Cross-contract conformance (bridge FHIR `Observation` ↔ sim `NormalizedObservation`) —
  **LIS-87**.
- Per-analyzer SD1 ingestion — **LIS-86**: the bridge parser quirks (PID-2 MRN capture +
  in-band 'Alarm' OBX → `DiagnosticReport` conclusion, not a result) are **landed** (PR #2,
  release `3.0.5`/`a98db88`). **Re-shaped 2026-07-04 (ADR-0018 / LIS-121–123, PR #16):** the
  MRN is no longer used *as* the accession — it rides the bundle as a FHIR `Patient`
  resource (reference-only subjects) while an id-less specimen gets a minted deterministic
  accession (`AccessionMinter`), and both parsers group per specimen (one
  Specimen+DiagnosticReport per OBR/O-record). The production code→LOINC seed **landed** in OE-core
  (`core/openelis` PR #11: liquibase `049-sd1-loinc-seed.xml` — SD1 analyzer +
  `AnalyzerTestMapping` + `Test.loinc`), pinned here. The raw-unit→UCUM `Quantity`
  coding (incl. U/L) **landed** via LIS-26 (PR #5, release `3.0.6`:
  `FhirBundleBuilder.UNIT_TO_UCUM`, raw `Quantity.unit` preserved beside `system`/`code`);
  LIS-28 (PR #6, release `3.0.7`) makes it registry-backed per analyzer
  (`AnalyzerEntry.unitToUcum`, pushed as `testUnitUcum`) with `UNIT_TO_UCUM` demoted to
  the fallback — OE-core doesn't send `testUnitUcum` yet (goes with the LIS-98 fix).
  Remaining: OBX-11 finality + bridge↔sim cross-contract are **LIS-87** (the Patient/MRN
  channel landed via ADR-0018 / PR #16; core-side surfacing of the identity is **LIS-97**,
  the sim grouping mirror **LIS-157**).
