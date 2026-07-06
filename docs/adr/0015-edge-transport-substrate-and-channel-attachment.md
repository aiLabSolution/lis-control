# ADR-0015 — Edge transport substrate: direct attachment of analyzer transports to the analyzer-bridge

- **Status:** Accepted (signed off 2026-06-30, M. Uy — integration lead; §Decision 5 ratified)
- **Date:** 2026-06-30
- **Deciders:** Marloe Uy (System / technical owner — integration lead)
- **Slice:** LIS-12 / S1.0 (Stage 1 — *settle the edge transport substrate before the framer thread*)
- **Supersedes / superseded by:** —
- **Relates to:** ADR-0008 (interface engine = reuse `openelis-analyzer-bridge`; stack = Java production runtime — **this ADR records the transport substrate *inside* that engine choice, the design point ADR-0008/DEC-04 left open**); ADR-0005 (MLLP framing + ACK modes, S1.1 / LIS-13 — the Stage-1 instance of the channel-config schema below); ADR-0009/0010 (ASTM E1381 codec / E1394 parser — Stage-2 protocol on the serial+ASTM substrate); ADR-0012 (raw-message archive + replay); core ADR-0003 (Result ingest contract — the `NormalizedObservation` DTO this ADR **reconciles** against the bridge's FHIR northbound, §Decision 5); ADR-0013 (Stage-1 milestone E2E — its "S1.0 substrate undecided" caveat is closed here); ADR-0014 (bidirectional QRD/QRF — the simulator substrate for the outbound path the bridge already exposes); threat-model TB-1/TB-2 + REQ-SEC-03 (channel isolation — wording this ADR sharpens); `LIS_BUILD_AND_INTEGRATION_RESEARCH.md` §5 (reference architecture), §13 open decision #6.

## Context

LIS-12 was titled "OIE channels vs bespoke drivers" — the interface-engine **build-vs-buy** question. That question is **closed**: ADR-0008 / DEC-04 ruled **reuse `openelis-analyzer-bridge`** (MPL-2.0, OpenELIS-family), *not* a Mirth/OIE fork and *not* bespoke-from-scratch. The SD-1 ruling (2026-06-29, M. Uy; dossier §SD-1) rescoped LIS-12 to the **genuinely-open** narrower question this ADR answers:

> **How do the non-HTTP analyzer transports — HL7/MLLP (Stage 1), serial + ASTM (Stage 2), and file / vendor-middleware (Stage 3) — attach to the reused bridge, and which module boundaries stay identical regardless of which transport a given analyzer uses?**

The dossier framed this around a premise — "the bridge is the *ASTM-HTTP Bridge*, so it is **HTTP-fronted**, and the open question is whether non-HTTP transports need a thin MLLP→HTTP shim / serial sidecar / file poller in front of it." **Reading the actual `aiLabSolution/openelis-analyzer-bridge` source falsifies that premise** (verified against the repo, namespace `org.itech.ahb`):

- The bridge is **not** HTTP-fronted on the inbound side. "HTTP" is the **northbound** (bridge → OpenELIS core) leg. The repo description is exact: *"middleware for analyzer protocols/transports (ASTM, HL7/MLLP, RS232 serial, file) forwarding to OpenELIS via HTTP."*
- The bridge **already implements native inbound listeners for every transport** in scope, decomposed cleanly into orthogonal `Transport` (HOW the bytes arrive) and `Protocol` (WHAT the bytes mean) enums (`model/Transport.java` = `TCP, MLLP, SERIAL, FILE, HTTP`; `model/Protocol.java` = `ASTM, HL7, CSV, UNKNOWN`):
  - **MLLP/HL7** — `mllp/HapiMLLPListener.java` (HAPI `SimpleServer`, dedicated thread, HAPI-generated `ACK`), gated by `org.itech.ahb.mllp.enabled` / `…mllp.port` (`MLLPConfig.java`, default 2575).
  - **Serial** — `serial/SerialPortListener.java` (jSerialComm) + `serial/SerialFrameBuffer.java` (an ASTM LIS2-A2 ENQ/STX/ETX/checksum state machine, and MLLP framing for serial-HL7), per-port baud/parity config (`SerialConfigurationProperties.java`).
  - **ASTM-over-TCP** — `ASTMServlet` listen-servers from the `astm-http-lib` dependency (LIS01-A on 12001, E1381-95 on 12011), started `@Async` by `controller/ASTMServerRunner(Trigger).java`.
  - **File** — `file/FileWatcher.java` (Apache Commons-IO polling) with a SQLite content-hash dedup + retry/terminal-state store (`file/SqliteFileStateStore.java`).
- Every transport converges on **one** seam and **one** pipeline (see §Decision 2), and the bridge already exposes the **outbound** order-download / host-query path (`/api/orders`, `/api/query`; `mllp/OutboundMllpClient.java`, `order/OutboundAstmClient.java`) that ADR-0014 models in the simulator.

So the substrate question is **not** "what shim do we build in front of an HTTP-only bridge" — it is "**do analyzers attach directly to the bridge's native listeners, or do we interpose anything**, and **what is the transport-invariant contract** the rest of the system binds to." This ADR fixes that, unblocking the framer/parser/normalization threads (S1.1+) on a settled substrate rather than a deferred guess.

## Decision

### 1. Analyzers attach **directly** to the bridge's native per-transport listeners. No shim, no sidecar, no bespoke channel engine.

For the pilot and the v1/v1.1 fleet (ADR-0008 / DEC-06):

| Stage | Fleet (ADR-0008) | Transport (`Transport`) | Protocol (`Protocol`) | Bridge listener | Inbound endpoint |
|---|---|---|---|---|---|
| **1 — pilot** | EDAN H60S (anchor), H99S, Seamaty SD1, RAYTO RT-7600 | **MLLP** | HL7 v2.3.1–v2.4 | `HapiMLLPListener` (HAPI `SimpleServer`) | analyzer = TCP client → bridge listens (EDAN port **7999**; bridge default 2575) |
| **2 — post-pilot v1.1** | ERBA EC90 | **SERIAL** (RS-232) and/or **TCP** | ASTM E1381/E1394 | `SerialPortListener` + `SerialFrameBuffer`; or `ASTMServlet` (LIS01-A / E1381-95) | serial port binding; or ASTM-TCP listen-server |
| **3 — post-pilot** | SNIBE MAGLUMI X3 *(amended 2026-07-06 — see note below)* | **TCP** (ASTM); MLLP for the HL7 fallback | ASTM E1394-97 (HL7 v2.5 documented alternative) | `ASTMServlet` listen-server (LIS01-A) + dedicated X3 framing profile (LIS-174) | analyzer = TCP client → bridge listens; the X3's native `Online` LIS interface is pointed at our bridge (**direct-attach, no middleware**) |

The MLLP path is the **pilot substrate** and is the only transport that must be *enabled and bench-proven for go-live*; serial/ASTM (Stage 2) and the X3's ASTM-over-TCP direct attach (Stage 3) are the **recorded forward path**, bench-validated now (against the ASTM simulators) but post-pilot for the live fleet under change control (DEC-06, SD-0). Enabling a transport is a config flag (`*.enabled=true`) + a restart; it ships no new code.

> **⮕ Amendment (2026-07-06, LIS-178) — Stage-3 X3 row re-baselined to native direct-attach.**
> The Stage-3 row originally read *"SNIBE MAGLUMI X3 + SnibeLis / FILE (middleware export) /
> CSV·ASTM / `FileWatcher` (watch dir + SQLite dedup) / SnibeLis-PC writes to a watched
> directory."* The owner directive of 2026-07-06 (Stage-3 epic redesign) drops the SnibeLis
> middleware entirely: the X3's built-in LIS interface (`Set → System Setting → Online`) speaks
> **ASTM E1394-97** (or **HL7 v2.5**) over TCP directly to whatever host it is pointed at, so
> the analyzer attaches to the bridge's native listeners like every other unit — which is
> exactly this ADR's **Decision 1** (direct attachment; no shim, no sidecar, no middleware).
> The FILE/`FileWatcher` route survives only as the LIS-34 last-resort contingency (if the X3
> firmware refuses a non-SNIBE host — unproven). Deltas the native path still needs: the X3's
> **simplified `ENQ/STX…ETX/EOT` session framing** (ACK per control token; no NAK/checksum/frame
> numbers by default, with an `Enable Checksum` analyzer-side toggle) requires a dedicated
> framing profile — **LIS-174**; channel registration (`bridge.analyzers`) — **LIS-175**; the
> HL7 fallback is a **proprietary SNIBE dialect** (`OUL^R22`/`OML^O33` on MLLP, *not* `ORU^R01`),
> so it needs its own parse path — **LIS-176**; native host-query/order-download — **LIS-177**;
> the bench capture that pins framing, timestamp indexing, and real Lis-IDs/units — **LIS-75**.
> Critical path: LIS-75 → {LIS-174, LIS-175} → LIS-32 → LIS-38. Fleet-scope side of the same
> amendment: ADR-0008 (DEC-06 amendment note, incl. the REQ-PRIV-09/DEC-17 DPA simplification).

**Rejected: an MLLP→HTTP shim / per-channel serial sidecar / standalone file poller** in front of an "HTTP-only" bridge (the dossier's hypothesis). It is unnecessary — the native listeners already exist — and it would add a second hop, a second process to validate (enlarging the L1/L2 surface ADR-0008 minimized), and a second place for framing/ACK bugs. The one place a thin terminator *could* still earn its keep — stronger per-channel OS-level isolation — is addressed as a **residual** under §Decision 4, not adopted for the pilot.

### 2. The transport-invariant module boundaries (the seam that stays identical regardless of substrate).

This is the AC's "framer / parser / normalization / ingest-contract module boundaries held identical regardless of substrate." In the bridge they are concrete:

```
                        TRANSPORT-SPECIFIC                 │  TRANSPORT-INVARIANT (identical for every substrate)
  ┌───────────┐   framer (de-frame the wire)              │
  │ analyzer  │──▶ MLLP de-frame  / ASTM ENQ-STX-ETX-cksum │
  └───────────┘    / serial buffer / file watch+dedup      │
                        │                                  │
                        ▼  raw application message          │
                 ┌──────────────────┐                       │
                 │  MessageEnvelope  │ ◀─── the convergence seam: every listener builds one
                 │ {protocol,transport,sourceId,rawMessage,sourcePort,resolvedAnalyzerId}
                 └──────────────────┘                       │
                        │                                  ▼
                        │            ┌──────────────────────────────────────────────────┐
                        └───────────▶│ MessageNormalizer (@Primary MessageRouter)         │ identify source →
                                     │   → HttpForwardingRouter                            │ corroborate hint →
                                     │      → HL7ResultParser / ASTMResultParser (parser)  │ enrich
                                     │      → FhirBundleBuilder  (normalization: code→LOINC)│
                                     └──────────────────────────────────────────────────┘
                                                          │  FHIR R4 transaction Bundle
                                                          ▼  POST application/fhir+json
                                              OpenELIS core  /analyzer/fhir   (the ingest contract)
```

- **Framer** = transport-specific (`HapiMLLPListener` / `SerialFrameBuffer` / `ASTMServlet` / `FileWatcher`). The only layer that knows the wire.
- **Parser** = protocol-specific, **not** transport-specific (`fhir/HL7ResultParser`, `fhir/ASTMResultParser` — the same HL7 parser serves MLLP *and* serial-HL7; the same ASTM parser serves serial-ASTM *and* ASTM-TCP). Selected by `Protocol`, decoupled from `Transport`.
- **Normalization** = the analyzer-code → LOINC/UCUM map carried on the registry entry (`AnalyzerEntry.codeToLoinc`, applied in `FhirBundleBuilder`). Identical regardless of transport.
- **Ingest contract** = the northbound is **a FHIR R4 transaction Bundle POSTed `application/fhir+json` to `/analyzer/fhir`** (`forward-http-server.uri` + `/fhir`; template `http://localhost:8080/api/OpenELIS-Global/analyzer/fhir`), with bounded retry (`max-attempts`/`backoff-ms`). Identical regardless of transport.

**The convergence seam is `normalizer/MessageEnvelope`.** Anything below it is substrate; everything above it is shared. This is the boundary S1.1+ slices build against, and the reason a new transport never touches the parser/normalizer/ingest layers.

### 3. Per-analyzer channel-config schema (documented; the Stage-1 instance is S1.1 / ADR-0005).

A "channel" in the bridge is the pairing of **(a) a transport binding** and **(b) an analyzer registry entry**. The AC's four attributes (transport, port, ACK mode, mapping profile) live as follows — this table is the documented schema S1.1 references:

| Attribute | Where it is configured | Source of truth | Stage-1 (EDAN H60S) value |
|---|---|---|---|
| **transport** | per-transport `@ConfigurationProperties` (`org.itech.ahb.mllp` / `.serial` / `.listen-astm-server` / `bridge.file`) | bridge config (`/app/configuration.yml`) | `MLLP` (`org.itech.ahb.mllp.enabled=true`) |
| **port / binding** | same | bridge config | `org.itech.ahb.mllp.port=7999` |
| **ACK mode** | HAPI application-ACK (success → `ACK`/AA via `generateACK()`; routing failure → NAK/AE) — **original-mode** for the whole v1 fleet (ADR-0005 §Notes) | bridge code (HAPI) + ADR-0005 | original `ACK^R01`, MSA-1 = AA/AE/AR |
| **protocol** | analyzer registry entry `expectedProtocol` / `RegistrationRequest.protocol` | **OpenELIS** (registry authority) | `HL7` |
| **source allow-list** | registry key = `sourceId` (IP / serial path / file-glob); `identifierPattern` corroborates the sender | OpenELIS registry | analyzer host:port |
| **mapping profile** | registry entry `codeToLoinc` / `testMappings` / `columnMappings` / `fileFormat` / QC (`qcRules`,`controlLots`) | OpenELIS registry | EDAN `99EDAN` → LOINC/UCUM seed (ADR-0011/0013) |

The registry is **OpenELIS-driven, not bridge-static**: the bridge pulls `/rest/analyzer/analyzers` on startup (`AnalyzerRegistryBootstrap`) and accepts live updates via `POST /api/analyzers/register` / `PUT /api/analyzers/sync` (`AnalyzerRegistrationController`). Therefore **adding or re-mapping an analyzer on an already-enabled transport is a config change with no core redeploy** (the user-story REQ behind REQ-SEC-03) — only **enabling a new transport or changing a listener port** needs a bridge restart (it is still config, not code: a `@ConditionalOnProperty`/`@Bean` re-evaluation).

### 4. REQ-SEC-03 channel-isolation — sharpen the wording into two tiers.

REQ-SEC-03 ("a bad driver cannot corrupt the core") and TB-2 ("the interface engine is architecturally separate from the core; each analyzer runs on its own channel") conflate two guarantees that the direct-attach substrate satisfies to **different** degrees. The ADR records the distinction so the threat-model/traceability wording and the Stage-5 L5 chaos proof target the right thing:

- **Tier 1 — bridge ↔ core (TB-2 crossing). STRUCTURALLY ISOLATED, holds now.** The bridge is a **separate process / container** from the OpenELIS core; the core's *only* ingest ingress for analyzer data is the validated **FHIR `/analyzer/fhir`** endpoint. A crashing, hung, or hostile bridge cannot write to the clinical DB except through validated, normalized FHIR records — exactly the REQ-SEC-03 / TB-2 guarantee. Direct-attach does **not** weaken this (a shim would not have strengthened it).
- **Tier 2 — channel ↔ channel *within* the bridge. THREAD-LEVEL, partial.** All listeners run as threads in one JVM (`AstmHttpBridgeApplication`); they share heap and lifecycle. Containment that exists: MLLP per-source-IP **rate limiting** (`RateLimitingReceivingApplication`, 10 msg/s/IP), per-message try/catch around each listener loop, the file channel's durable retry + `rejected_bundles` capture, and per-channel health indicators (`management.health.{mllp,serial,filewatcher,httpforward}`). Containment that is **missing / residual** (inherited from the reused bridge, per ADR-0008 "reusing the bridge means inheriting its code as a validated object"):
  - rate-limiting is **MLLP-only** — serial / ASTM-TCP / file / HTTP have none;
  - the filesystem dead-letter queue (`util/DeadLetterWriter`) is **wired but never invoked** — actual rejection capture is the SQLite `rejected_bundles` table only. **Closed 2026-07-03** by LIS-88 (bridge PRs `openelis-analyzer-bridge#10`/`#11`, pin `3.0.9`/`fb2167c`): `DeadLetterWriter` was **removed** (the transparent-pipe rule had retired its only intended use case) and `rejected_bundles` is documented in the bridge README as the single rejection store of record — now fed by **every** transport, FILE included;
  - unknown-source messages are **forwarded anyway** (the "transparent-pipe" rule in `MessageNormalizer`), so the `sourceId` allow-list is *advisory*, not enforcing — a TB-1 **spoofing** gap (a rogue device on an enabled port is ingested);
  - one channel can still starve the shared JVM (CPU/heap/GC) — there is no per-channel OS resource isolation.

  **Decision:** accept Tier-2 as-is for the **pilot** (single-anchor, MLLP-only, smallest surface — ADR-0006/0008), and record the residuals as **change-controlled hardening** to be proven at the **L5 chaos test in Stage 5** (REQ-SEC-03 is L5-verified per the traceability matrix). The "bad driver cannot corrupt the core" claim is carried by **Tier 1** (structural), which the chaos test fault-injects across TB-2; the intra-bridge "one channel cannot starve another" claim is explicitly the *weaker, residual* one. (Wording delta proposed to threat-model TB-2 / traceability REQ-SEC-03 row — flagged for review, see Consequences.)

### 5. Northbound contract reconciliation — FHIR is the production wire; `NormalizedObservation` (core ADR-0003) is its semantic contract. **[RATIFIED 2026-06-30 — M. Uy]**

Two northbound contracts exist in the codebase and must be reconciled by this ADR, because "the ingest contract" is one of the module boundaries S1.0 fixes:

- **Production data-path (this substrate):** the Java bridge emits a **FHIR R4 transaction Bundle** (`FhirBundleBuilder`: Device + Specimen + DiagnosticReport + Observation[]) to `/analyzer/fhir` — wired, and OpenELIS already ingests FHIR. **Amended 2026-07-04 (ADR-0018 / LIS-121–123):** the bundle is now Device + Patient (when the wire carries identity) + one Specimen + DiagnosticReport + Observation[] **per wire specimen** — multi-order transmissions no longer collapse onto a single accession, and id-less specimens get a minted deterministic accession instead of the shared `HL7-UNKNOWN`/`ASTM-UNKNOWN` sentinels.
- **Core ADR-0003 / edge-sim ADR-0013:** define a language-neutral **`NormalizedObservation` DTO** (`value` + analyzer-native `rawCode`/`rawUnit` beside `loinc`/`ucumValue` + `status`) with a committed JSON-Schema, persisted by `ResultIngestService.ingest`, and the Python simulator emits **that DTO**.

These are **not the same wire.** The reconciliation this ADR records (**ratified 2026-06-30, M. Uy**):

> **FHIR-over-HTTP (`/analyzer/fhir`) is the production edge→core ingest contract.** `NormalizedObservation` (ADR-0003) is the **semantic contract** — the field-level correspondence (value · raw code/unit · LOINC/UCUM · status) every normalized result carries — and is the contract the **Python simulator** speaks. The two are reconciled because a FHIR `Observation` *is* the production serialization of a `NormalizedObservation`: `Observation.code.coding` carries the LOINC **and** the analyzer-native code, `Observation.valueQuantity` carries the UCUM value/unit, and `Observation.status` carries lifecycle. ADR-0003's "the edge maps to this contract over whatever transport S1.0 picks" is hereby answered: **S1.0 picks FHIR-over-HTTP for the production bridge; the DTO is the simulator's analog and the semantic invariant both sides honor.**

Why this was the recommendation and not "make the bridge emit the DTO": the bridge's FHIR path is field-proven and already accepted by core; re-plumbing it to a bespoke DTO endpoint would discard a working, OpenELIS-native ingest for a contract whose *purpose* (ADR-0003) was correspondence, not a specific wire. **Ratified 2026-06-30 (M. Uy).** The actions this implies: (a) **annotate core ADR-0003** to state the FHIR `Observation` is the production serialization of a `NormalizedObservation` — **done in this PR**; (b) add a thin **cross-contract conformance check** that the bridge's FHIR Observation and the simulator's `NormalizedObservation` carry the same fields (the analog of ADR-0013's shared JSON-Schema, one level up) — **tracked as a follow-up implementation slice** (not this docs-only slice).

## Consequences

**Positive**
- The substrate is settled on the **simplest, already-built** option: analyzers attach to the bridge's native listeners; no new process, no shim, no second validation object — consistent with ADR-0008's "smallest pilot surface."
- S1.1+ (framer/parser/normalization) build against a **concrete, transport-invariant seam** (`MessageEnvelope` → normalize → FHIR `/analyzer/fhir`); a new analyzer or a new transport never touches the parser/normalizer/ingest layers.
- The **channel-config schema** is documented and mapped to real bridge config keys + the OpenELIS registry, satisfying the "config-not-redeploy" user story for the common case (new analyzer on an enabled transport).
- REQ-SEC-03 gets **precise, falsifiable wording** (Tier-1 structural / Tier-2 thread-level) for the Stage-5 chaos proof, instead of a single conflated claim.
- The northbound contract is **named** (FHIR `/analyzer/fhir`) and reconciled with ADR-0003 — closing the "S1.0 substrate undecided" caveat that ADR-0013/0014 and core ADR-0003 all defer to.

**Negative / costs / residuals (inherited from the reused bridge — ADR-0008)**
- **Tier-2 isolation is thread-level, not process-level** (shared JVM); rate-limiting is MLLP-only; the source allow-list is advisory (unknown sources forwarded — a TB-1 spoofing gap). Recorded as change-controlled hardening (LIS-91), L5-proven in Stage 5. ~~The filesystem DLQ (`DeadLetterWriter`) is inert~~ — **closed 2026-07-03** by LIS-88 (bridge PRs `openelis-analyzer-bridge#10`/`#11`, pin `3.0.9`/`fb2167c`): the inert writer was removed and the SQLite `rejected_bundles` table is the documented single rejection store of record.
- **FILE deviates from the shared pipeline** — `FileMessageHandler` parses and POSTs the FHIR bundle itself, **bypassing `MessageNormalizer`/`HttpForwardingRouter`** (same payload + same `/analyzer/fhir` endpoint, but a parallel code path). It honors the *ingest contract* but breaks the "identical module boundary" principle of §Decision 2. Flagged for a follow-up to route FILE through the common normalizer (Stage-3 prep). **Closed 2026-07-03** by LIS-88 (bridge PRs `openelis-analyzer-bridge#10`/`#11`, pin `3.0.9`/`fb2167c`): structured parsing stays in the FILE listener (binary formats + analyzer-specific column mappings can't parse from a wire string), but each parsed accession now enters the §Decision 2 seam as a `MessageEnvelope` (new `parsedResults` field) and flows through `MessageNormalizer` → `HttpForwardingRouter` — gaining the ingest contract's bounded retry, `rejected_bundles` capture, and routing metrics, with the POSTed bundle unchanged.
- **ASTM E1381-95 listener config key is mismatched** (`configuration.yml` sets `org.itech.ahb.listen-astm-e1381-95-server.port` but the binding prefix is `org.itech.ahb.listen-astm-server.e1381-95`), so the YAML is ignored and the default 12011 is used. A Stage-2 bench trap; flagged for a bridge-config fix before Stage-2 bench. **Closed 2026-07-02** by LIS-26 (bridge PR `openelis-analyzer-bridge#5`, pin `3.0.6`/`c7382e4` via `lis-control#57`): the YAML now nests `e1381-95.port` under `listen-astm-server` so the key binds, and `E1381_95` additionally goes through establishment + the framed compliant receive path in `GeneralASTMCommunicator.receiveProtocol` (it previously fell to the non-compliant read).
- **Northbound reconciliation (§Decision 5) — ratified 2026-06-30 (M. Uy).** FHIR-over-HTTP is the production ingest contract; core ADR-0003 is annotated in this PR; the cross-contract conformance check is tracked as a follow-up implementation slice.
- Adopting the bridge's transports commits us to the bridge's framing/ACK implementations (HAPI for MLLP, `astm-http-lib` for ASTM); swapping them later is a change-control / revalidation delta (REQ-QMS-03) — deliberate, per ADR-0008.

## Alternatives considered

- **MLLP→HTTP shim / serial sidecar / file poller in front of an "HTTP-only" bridge** (the dossier's SD-1 hypothesis). **Rejected** — the premise is false (the bridge has native listeners), and the shim adds a hop, a process to validate, and a second framing/ACK surface for no benefit. The only thing it would buy — OS-level per-channel isolation — is a Tier-2 residual better addressed under change control if the fleet outgrows the single-process model.
- **Bespoke per-protocol drivers on a raw HL7/ASTM toolchain (HAPI / python-hl7)** — rejected by ADR-0008/DEC-04 already; re-listed here only to confirm S1.0 does not reopen it.
- **Adopt an Open Integration Engine (Mirth/OIE/BridgeLink) as the channel layer** — rejected by ADR-0008; heavier to operate/validate than the OpenELIS-family bridge for the pilot fleet; revisitable under change control if channel count/variety grows (research §6/§13).
- **Make the bridge emit core ADR-0003's `NormalizedObservation` DTO instead of FHIR** — rejected (§Decision 5): discards a working, OpenELIS-native FHIR ingest for a contract whose purpose was correspondence; FHIR `Observation` already carries the DTO's fields.
- **Run each channel as its own OS process now (true Tier-2 isolation)** — deferred: unnecessary for the single-anchor MLLP pilot; revisit under REQ-QMS-03 if the chaos test (L5) shows intra-bridge starvation, or when the fleet scales beyond a few channels.

## Notes / references

- **Bridge source (verified):** `aiLabSolution/openelis-analyzer-bridge` (`org.itech.ahb`). Transport/Protocol model: `model/Transport.java`, `model/Protocol.java`. Listeners: `mllp/HapiMLLPListener.java` (+ `MLLPConfig`, `HapiReceivingApplication`, `RateLimitingReceivingApplication`), `serial/SerialPortListener.java` (+ `SerialFrameBuffer`, `SerialConfigurationProperties`), `controller/ASTMServerRunner(Trigger).java` (+ `ASTM{E138195,LIS1A}ListenServerConfigurationProperties`), `file/FileWatcher.java` (+ `SqliteFileStateStore`, `FileConfig`). Seam + pipeline: `normalizer/MessageEnvelope.java`, `normalizer/MessageNormalizer.java`, `routing/{MessageRouter,HttpForwardingRouter}.java`, `fhir/{HL7ResultParser,ASTMResultParser,FhirBundleBuilder}.java`, `util/OeApiClient.java` (registry pull only). Registry/config: `config/AnalyzerRegistryConfig.java` (`AnalyzerEntry`), `controller/AnalyzerRegistrationController.java`, `startup/AnalyzerRegistryBootstrap.java`, `config/properties/HTTPForwardServerConfigurationProperties.java`, `src/main/resources/application-{prod,dev}.yml`, repo-root `configuration.yml`. Outbound: `mllp/OutboundMllpClient.java`, `order/OutboundAstmClient.java`, `controller/{OutboundOrderController,AnalyzerQueryController}.java`.
- **ACK mode:** HAPI `SimpleServer` application-ACK; the whole v1 fleet is **original-mode** (ADR-0005 §Notes — enhanced-mode stays simulator-tested, hardware-unproven).
- **Bench captures pending** (do not block this ADR): EDAN H60S operator port (7999 documented), Seamaty SD1 operator-set port + MLLP framing, ERBA EC90 RS-232 baud/pinout — `docs/testing/stage-1-3-machine-access-checklist.md` (LIS-74).
- **This slice ships no analyzer behavior** (the LIS-12 contract) — it records the substrate, the module boundaries, the channel-config schema, and the REQ-SEC-03 wording, and unblocks the framer thread (S1.1+). The bridge-code residuals it surfaces (FILE pipeline deviation, ASTM port key, inert DLQ, MLLP-only rate-limit, advisory allow-list) are recorded here and tracked as their own change-controlled follow-ups, not fixed in this docs-only slice.
