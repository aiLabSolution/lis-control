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
- **Pin:** release **`3.0.7`** (`fe391a7`) — the LIS-28 bridge change (PR
  `openelis-analyzer-bridge#6`: registry-backed raw-unit→UCUM mapping —
  `AnalyzerEntry.unitToUcum` feeds FHIR `Quantity.system/code` while `Quantity.unit`
  preserves the raw analyzer text, with fallback to the legacy common-unit map; plus
  `testUnitUcum` wired through both the `/register` and full-state `/sync` push paths
  so an OE sync cannot wipe it — the LIS-98 bug class. OE-core does not *send*
  `testUnitUcum` yet; that lands with the LIS-98 fix). Follows `3.0.6` (`c7382e4`,
  LIS-26: ERBA EC90 ASTM normalization — E1381-95 framed compliant receive,
  e1381-95 config-key fix, UCUM `Quantity` coding) on top of the EDAN H90-series
  parse profile (PR #4) and the LIS-95 SD1 QC/calibration gate (PR #3).
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
go-live (EDAN H60S anchor, port 7999; bridge default 2575). Serial/ASTM (Stage 2) and file
(Stage 3) are the recorded forward path — bench-validated against the simulators, post-pilot
for the live fleet under change control (DEC-06 / SD-0). Enabling a transport is a config flag
+ restart; it ships no new code.

## Component decisions / references

- **ADR-0015** (umbrella) — edge transport substrate: direct attachment to the bridge's native
  listeners; channel-config schema; REQ-SEC-03 two-tier isolation; FHIR northbound.
- **ADR-0008** (umbrella) — interface engine = reuse the bridge; Java production stack; v1 fleet.
- **ADR-0005** (umbrella) — MLLP framing + ACK modes (original-mode for the v1 fleet).

## Open items / residuals (ADR-0015 §4, tracked as follow-ups)

- Intra-bridge isolation is thread-level (shared JVM); rate-limiting is MLLP-only; the
  filesystem DLQ (`DeadLetterWriter`) is inert; the source allow-list is advisory (TB-1
  spoofing gap). Change-controlled hardening, L5-proven in Stage 5 — **LIS-88 / LIS-89**.
- FILE channel bypasses the shared normalizer — **LIS-88**. (The ASTM E1381-95 config-key
  mismatch, originally here, is **closed** by LIS-26 / PR #5, release `3.0.6`: the key now
  binds under `listen-astm-server.e1381-95` and `E1381_95` uses the framed compliant
  receive path.)
- Cross-contract conformance (bridge FHIR `Observation` ↔ sim `NormalizedObservation`) —
  **LIS-87**.
- Per-analyzer SD1 ingestion — **LIS-86**: the bridge parser quirks (PID-2 MRN fallback +
  in-band 'Alarm' OBX → `DiagnosticReport` conclusion, not a result) are **landed** (PR #2,
  release `3.0.5`/`a98db88`). The production code→LOINC seed **landed** in OE-core
  (`core/openelis` PR #11: liquibase `049-sd1-loinc-seed.xml` — SD1 analyzer +
  `AnalyzerTestMapping` + `Test.loinc`), pinned here. The raw-unit→UCUM `Quantity`
  coding (incl. U/L) **landed** via LIS-26 (PR #5, release `3.0.6`:
  `FhirBundleBuilder.UNIT_TO_UCUM`, raw `Quantity.unit` preserved beside `system`/`code`);
  LIS-28 (PR #6, release `3.0.7`) makes it registry-backed per analyzer
  (`AnalyzerEntry.unitToUcum`, pushed as `testUnitUcum`) with `UNIT_TO_UCUM` demoted to
  the fallback — OE-core doesn't send `testUnitUcum` yet (goes with the LIS-98 fix).
  Remaining: Patient/MRN channel + OBX-11 finality + bridge↔sim cross-contract are **LIS-87**.
