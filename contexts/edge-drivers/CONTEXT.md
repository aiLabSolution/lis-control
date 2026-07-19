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
- **Pin:** untagged **`4b9f757`** — LIS-232 Lifotronic H9 edge integration
  (PR `openelis-analyzer-bridge#43`). The H9's byte-positional frames cross the whole
  normalize → route → FHIR path without a String round-trip: `SerialMessageHandler` maps the
  framing-selected mode directly to `Protocol.LIFOTRONIC_H9` (D3 — `ProtocolDetector`
  bypassed; its String heuristic reads S/Q/C bodies as UNKNOWN), `MessageEnvelope` gains an
  immutable `byte[] rawBytes` (D2 — H9 sets exact frame + lossless ISO-8859-1 display; all
  other transports unchanged), and `HttpForwardingRouter` grows the `LIFOTRONIC_H9` branch
  (D4 — `H9ResultParser.parse(rawBytes)`; recorded deviation: the slice text's
  `parse(rawBytes, rules)` signature was not adopted — the parser itself emits the
  hardcoded IFCC pair `59261-8`/`mmol/mol`, and the registry `codeToLoinc`/`unitToUcum`
  resolvers still apply downstream in `FhirBundleBuilder`. Net effect: with no registry
  mapping for `59261-8` (the shipped state) the bundle carries a **system-less** coding —
  OE derives UNMAPPED/PARTIAL, not NORMALIZED (ADR-0015 §5) — while a registry mapping
  keyed on `59261-8`/`mmol/mol` CAN rewrite the H9 coding; the e2e test's substring
  assert cannot tell the two apart. The S7/LIS-235 terminology-sign-off concern.). D8:
  production inbound raw archive per
  **ADR-0022** (content-addressed SHA-256, atomic durable write + provenance sidecar,
  first-wins immutability + tamper evidence, encryption-at-rest mode, rejection↔digest
  correlation, orphan-payload heal, `DUPLICATE_SUPPRESSED` once per digest); H9 traffic is
  **fail-closed without the archive** (`bridge.archive.enabled`, shipped default `false`).
  The serial rate-limit is spent before the archive fsyncs, but a byte-identical resend
  still reaches dedup — retry-does-not-duplicate holds. Parse refusals log a digest-linked
  `getSafeSummary()` only; the unredacted field window survives in the `rejected_bundles`
  row + encrypted sidecar (adversarial P1: raw frame bytes reached application logs —
  fixed in two passes, the second converting five further throw sites and inverting the
  guard into an allowlist over the parser's real label vocabulary, plus an e2e logback
  assertion). Three review passes (2× REQUEST_CHANGES on real findings); full suite at the
  pin **1041/0/0/7** (1036/0/0/7 on the PR #43 branch pre-merge; the pin's `test` check is
  green — its `build-and-push-dev-image` check fails on missing registry credentials,
  pre-existing infra). Cross-level fixture anchor `c8941a55…0d98f2` byte-identical with
  `edge/sim` (umbrella #158 + pin-bump #176). Close-out: AC1 automation / OE-staging AC4
  half re-scoped to **LIS-305**; AC2/AC3 coverage follows as bridge PR #51 (test-only)
  plus its pin bump.
- **Intervening pins (not genealogized here):** `de22890` (LIS-133, PR #38) → `d2b25bc`
  (**LIS-230 H9 codec/framer**, #39) → `0783b53` (LIS-87, #40) → `9292566` (LIS-252, #42) →
  `1426c68` (**LIS-231 H9 parser**, #41) → `7f6e855` (LIS-265, #46) → `6613968` (LIS-38, #45)
  → `75230de` (LIS-268, #47) → `d3e0f97` (LIS-267 durable X3 inbound, #48) → `8ee93ea`
  (LIS-271, #44) → `9c6e2c7` (LIS-277, #49); the H9 pair (framer, parser) are the LIS-232
  integration's direct precursors — see the [S3.H9] epic.
- **Prior genealogized pin:** untagged **`940e3a0`** — LIS-110 vendor-aware MSH-16 result-type profile
  (PR `openelis-analyzer-bridge#37`). `HL7ResultParser.fromEdanMsh16`: EDAN H60/H90-series
  messages (existing `isEdanH90Series` announce gate) map MSH-16 `0`/blank → PATIENT and
  `1` → QC; every other value — the documented non-result frames `2`=test-connection /
  `3`=host-query (`EDAN\WI\82-01.54.460907` §3.2.1, bench-corroborated 2026-07-06/07), the
  undispositioned `4`=protein-control (LIS-224) / `1000`, and unknowns — is held out of the
  patient stream as QC (emitted PRELIMINARY per ADR-0019). The EDAN **QC OBR layout**
  (460907 §3.2.3, trusted only on MSH-16 exactly `"1"`): lot = OBR-13, level = OBR-3 (raw
  digit), accession = OBR-2 QC file No. only (blank → deterministic mint — never the OBR-3
  level digit); the OBR-20 worklist-barcode join (LIS-149) is gated to PATIENT frames so a
  held control group can never be re-keyed onto a patient order. SD1/generic `fromMsh16`
  and the SNIBE branch byte-for-byte unchanged. Sim mirror in-tree (`oru._result_type`
  edan branch, `normalize_report` QC re-kind widened to ASTM-or-EDAN; SD1 HL7-QC re-kind
  gap deliberately kept, tracked LIS-95). Adversarial review: pass-1 REQUEST_CHANGES
  (KB-citation P1 + two P2s) → fixed in `21826fe` → pass-2 APPROVE. Full suite at the pin
  **887/0/0/5**, `edge/sim` **343** (local runs recorded; N.B. the "bridge has no CI"
  note originally here was wrong — bridge `test.yml` has existed since 2025-12-04;
  corrected in LIS-304).
  `1=QC` + the §3.2.3 layout are protocol-documented but not yet wire-confirmed (no
  QC-mode bench capture) — deviation recorded in `docs/runbooks/edan-h60s-bench-conformance.md`.
- **Intervening pins (not genealogized here):** `002210a` → `f051a3c` (LIS-44, PR #32) →
  `7a5079ae` (LIS-45, #33) → `0bcab14` (LIS-214, #34) → `1023e7a8` (LIS-213, #35) →
  `ca68160` (LIS-46, #36) — the HIS-outbound ORU^R01 tail (delivery ⟺ MSA-1=AA, durable
  store-and-forward queue, 409 collision surfacing, anchored ACK classification, restart
  chaos test); see the LIS-44/45/46/213/214 issues and umbrella PRs #124–#127/#130.
- **Prior genealogized pin:** untagged **`002210a`** — LIS-176 SNIBE MAGLUMI X3 HL7 v2.5 `OUL^R22` native
  fallback parse path (PR `openelis-analyzer-bridge#28`). A MAGLUMI-gated dialect branch in
  `HL7ResultParser` (`isSnibeX3` = MSH-3 component-1 `equalsIgnoreCase("MAGLUMI")`, decided
  before any standard MSH read): shifted MSH metadata (control-id = MSH-6, datetime = MSH-4,
  vs standard MSH-9/MSH-7), SPM-driven accession grouping (`SPM-2`), and `SPM-11` role routing
  (`P` → PATIENT, `Q`/unknown/missing → QC — kept out of the patient/Observation stream via a
  per-group `resultType` so the `messageResultType=PATIENT` fallback is never reached for a
  SNIBE group). `OBX-7` → FHIR reference range and `OBX-8` → interpretation for non-EDAN
  standard-position HL7; the router accepts a `Protocol.HL7 + Transport.MLLP` envelope through
  the shared IP-keyed `AnalyzerRegistryConfig` + FHIR normalization (no bypass, no auth change).
  Branched off `ccc5f26` (before LIS-112); `origin/develop`'s LIS-112 "handle EDAN OBX payloads"
  (`a1182b9`) was merged into the branch — the `parseObxSegment` OBX-7/OBX-8 block resolves to
  LIS-112's superset (reference-range-for-all + computed EDAN-numeric abnormal flag), which for
  `edanH90=false` (SNIBE) reads `OBX-8` and applies `OBX-7` exactly as LIS-176 intended, with no
  EDAN regression (`git diff a1182b9 002210a` on `FhirBundleBuilder` empty). Landed with
  adversarial APPROVE (no P0/P1; conflict resolution verified faithful); full suite at this
  merged pin **803/0/0/5**, `edge/sim` **328** (local runs recorded; stale "no CI" note
  corrected in LIS-304).
  **Synthetic fixture coverage only — real X3 `OUL^R22` wire proof, the exact MSH-3 sending-app
  token, and the shifted MSH layout remain LIS-75 bench work** (adversarial P2: the whole
  QC-safety property depends on `isSnibeX3` firing); AC-1/AC-2 do not graduate until then, slice
  stays OPEN. Out of scope of this PR: `OBX-11` result finality (LIS-179) and `OML^O33`
  order-download / host-query (LIS-177) — this is the `OUL^R22` result/QC ingest path only. Sits
  on top of the intervening `a1182b9` (LIS-112 EDAN OBX payloads: histogram attachments +
  numeric-range abnormal-flag derivation) and `ccc5f26` (LIS-185 EDAN OBR-14 lot-number gate,
  PR #26), and the LIS-149 return-leg `30b11c8` / LIS-182 `15feb08` / LIS-175 `8d4f75a` that
  landed between `963b39a` below and here.
- **Prior pin:** untagged **`963b39a`** — LIS-174 SNIBE MAGLUMI X3 native simplified-envelope
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
  local runs recorded; stale "no CI" note corrected in LIS-304). **Gap 4 of the LIS-119 era is hereby landed
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
analyzer ──▶ framer (transport-specific)           ──▶ MessageEnvelope (convergence seam;
             HapiMLLPListener / SerialFrameBuffer        │  H9 carries byte[] rawBytes)
             (incl. H9 byte framing) / ASTMServlet        ▼
             / FileWatcher                  MessageNormalizer → HL7ResultParser / ASTMResultParser
                                            / H9ResultParser (byte-positional, rawBytes)
                                            → FhirBundleBuilder (codeToLoinc)
                                            ──▶ FHIR R4 Bundle → POST /analyzer/fhir → OpenELIS core
```

- **Framer** = transport-specific (the only layer that knows the wire).
- **Parser** = protocol-specific, not transport-specific.
- **Normalization** = analyzer-code → LOINC/UCUM, carried on the **OpenELIS analyzer registry**
  entry (`AnalyzerEntry.codeToLoinc`); the bridge pulls `/rest/analyzer/analyzers` on startup.
  Adding/re-mapping an analyzer on an enabled transport is **config, not redeploy**. LIS-268
  adds one explicit deploy-liveness exception: a complete deploy-kit source binding marked
  `LOCAL_BOOTSTRAP` survives unrelated OE snapshots until OE claims that exact source key;
  an analyzer-ID collision at a different source rejects the sync loudly. Unmarked entries
  remain OE-owned and stale-removable, and the entire local entry (including `qcRules` and
  code/unit maps) is preserved.
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
  The sim grouping + deterministic-minting mirror **landed via LIS-157** for HL7 OBR
  and ASTM O-record batches, including per-group blank/QC/calibration typing. Remaining:
  OBX-11 finality + bridge↔sim cross-contract are **LIS-87** (the Patient/MRN channel
  landed via ADR-0018 / PR #16; core-side surfacing of the identity is **LIS-97**).
