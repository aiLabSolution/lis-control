# MAGLUMI X3 staging end-to-end demo — LIS-39

Demonstration of the SNIBE MAGLUMI X3 native Online ASTM channel deployed as a site
stack (pinned OpenELIS core + pinned analyzer bridge) and driven end to end with the
LIS-75 bench-graduated fixture. No SnibeLis middleware is present anywhere on the path:
the X3 speaks ASTM E1394-97 directly to the bridge, which forwards FHIR to OpenELIS.

**Status: DEMONSTRATED WITH GAPS.** The transport path is proven end to end on a live
stack — wire → bridge → `/analyzer/fhir` → staged → **technician-accepted final Result**.
Two acceptance criteria remain open in the recorded run: AC2 needs a fresh run on the
current versioned X3 dictionary (the captured run used the older proxy map), while AC3
still depends on a bench-proven QC marker (LIS-266). Per-AC verdicts are below.

## AC verdict summary

| AC | Verdict | Basis |
|---|---|---|
| 1 — result reaches a final OpenELIS Result | **MET** | 3 rows at `Technical Acceptance`, `run/final-results.txt` |
| 2 — raw evidence preserved + LOINC/UCUM populated | **PARTIAL** | raw code/unit/value/range/flag all preserved; LOINCs are proxy codes; one UCUM blank |
| 3 — QC routed out of the patient stream | **NOT MET** | discriminator unproven on the wire (LIS-266) |
| 4 — staging configuration recorded | **MET** | this document; source identity live-confirmed |
| 5 — raw archive + replay reproduce the result | **MET** | sha256-anchored fixture, `run/prove-site-x3-e2e.log` |
| 6 — reverse-mapping notes versioned + linked | **MET** | this document; git-pin versioning |

## Captured-run and current reproducible pins

The "mapping profile version" this demo records is the git pin — there is no separate
`profileVersion` key in the X3 profile. The files in `run/` were captured against these
historical revisions. The deploy-kit entry is the proof-branch head actually executed,
not the older umbrella gitlink that preceded the acceptance script:

| Component | Path | Pin |
|---|---|---|
| OpenELIS core | `core/openelis` | `25e06ea4a1f7ba25896e176b87b546ff87e4bbcc` |
| Analyzer bridge | `edge/drivers` | `46e57b9fc631d727eb977b2740de119b9343c04f` |
| Deploy kit proof branch | `deploy/kit` | `fc5977899c88285548e969eaddcfae8a120d617d` |

The umbrella commit carrying this record now reproduces the approved successor stack:

| Component | Path | Current pin |
|---|---|---|
| OpenELIS core | `core/openelis` | `810bf24b34ac688b8cc187527bc46ac5dd3996aa` |
| Analyzer bridge | `edge/drivers` | `356bdb289000697c6a647e5dfab5d98879502eee` |
| Deploy kit | `deploy/kit` | `377f0403fe1fea06d11a09f4fb45f740cc01a2f6` |

The current stack retains the captured evidence as historical proof; it does not relabel
the old logs as a run against the successor pins. Mapping-profile sources at the current
pins are:

- `deploy/kit/configs/analyzer-profiles/astm/snibe-maglumi-x3.json` — **authoritative**,
  mounted read-only into OpenELIS at `/data/analyzer-profiles`.
- `core/openelis/projects/analyzer-profiles/astm/snibe-maglumi-x3.json` — non-authoritative
  mirror; drift between the two is gated by the `deploy-kit-config` workflow against
  `deploy/ci/profile-drift-allowlist.txt` (currently empty, so they must be identical).
- `edge/drivers/configuration.yml` — the bridge-side `bridge.analyzers` channel including
  the versioned `codeToLoinc` / `unitToUcum` maps.
- `edge/sim/fixtures/snibelis-maglumi-x3-result-upload/` — the signed replay fixture
  (`message.astm`, sha256 `cccd2eec47ccdce53997adfa0fa7c8ee5c082b577806dbec574700af96992054`).

## AC4 — deployed staging configuration

### Source binding and analyzer identity

The bridge keys the X3 registry entry on the **source IP it observes**, not on any
identity the analyzer sends. `edge/drivers/configuration.yml` ships the channel under a
bracket-escaped source-IP key with `id: SNIBE-MAGLUMI-X3-001`, `name: "Maglumi X3"`
(the bench-verified H-5 sender), and `expectedProtocol: ASTM`.

Two facts govern this and are both bench-established, not assumed:

- **Identity is never used for routing.** LIS-75 AC6 (16 capture sessions,
  `evidence/bench/maglumi-x3/20260717-ac6-hostid-mismatch/`) proved the X3 enforces **no**
  host-id match: with `Host ID` set to `NOTLIS` the analyzer stamped `NOTLIS` into H-10
  and delivered the full batch anyway. H-record identity fields are operator-editable free
  text — informational only. The `identifierPattern` in the config is explicitly marked
  diagnostic.
- **Docker NAT rewrites the client source IP.** For a containerized demo the bridge observes
  a gateway address (e.g. `172.21.0.1`), not the analyzer's LAN IP. The shipped config value
  `192.0.2.10` is a TEST-NET-1 placeholder and is never routable; the demo run calibrates the
  observed source and registers that. `LIS_SITE_X3_SOURCE` sets the bootstrap identity;
  steady-state identity comes from the OpenELIS analyzer record via registry sync.

### Port binding, framing, and checksum mode

The X3 listener bean is **opt-in**: `edge/drivers/configuration.yml` ships the
`org.itech.ahb.listen-astm-server.snibe` block commented out, and the bean is created only
when its `port` key is present, so sites without an X3 never open the port. The demo enables
it via the deploy kit (`LIS_SITE_X3_BIND`, default host port `12021`; the bridge's own
compose maps `12020:12021`).

| Setting | Demo value | Note |
|---|---|---|
| Listener port | `12021` (container) | Host bind via `LIS_SITE_X3_BIND` |
| Framing | SNIBE simplified envelope (LIS-174) | `ENQ/STX/payload/ETX/EOT`, ACK per control token, CR-only separators, no NAK, no frame numbers |
| Checksum | `false` | Mirrors the analyzer's Online-screen `Enable Checksum` toggle; `true` delegates the connection to the compliant E1381-95 path |
| Query / order download | **`direction: upload-only`** | The send half (`OML^O33`, LIS-177) is **not implemented**. Do not set bidirectional. |
| `so-timeout-seconds` | `10` | Bounds first-ENQ and in-envelope reads, **not** idle time between envelopes |

### Ingest endpoint

The bridge forwards a FHIR R4 transaction Bundle to OpenELIS at
**`/api/OpenELIS-Global/analyzer/fhir`**, which sits behind the module interceptor and
therefore requires an admin-capable account (`LIS_SITE_OE_USER`).

> **Discrepancy to resolve:** the bring-up runbook
> `docs/runbooks/snibe-maglumi-x3-bridge-openelis-bringup.md` describes X3 traffic landing on
> `/analyzer/astm`, which conflicts with the FHIR-northbound ingest contract used by ADR-0015,
> core ADR-0003, and the site-stack e2e. This demo exercises the **`/analyzer/fhir`** path.
> The runbook needs correcting or an explicit note that it describes a raw-protocol forward.

## AC6 — versioned X3 reverse-mapping notes

### Bench-verified dictionary (LIS-38 AC1, Pinote QA-approved)

Only the three assays captured on the bench are real. **The LOINC property axis must match
the unit the analyzer actually reports** — this is keyed on the unit, never on the bare code
string. LIS-299 corrected two wrong-axis codes that had passed QA at merge; the corrected
values below are what the pinned sources carry (verified in both
`edge/drivers/configuration.yml` and the fixture manifest at these pins).

| Wire code | Unit (UCUM) | LOINC | Property | LIS-299 change |
|---|---|---|---|---|
| `FT3` | `pmol/L` | **`14928-6`** | SCnc (moles/volume) | corrected from `3051-0` (MCnc — wrong axis) |
| `FT4 II` | `ng/dL` → `ng/dL` | **`3024-7`** | MCnc (mass/volume) | corrected from `14920-3` (SCnc — wrong axis) |
| `TSH II` | `uIU/mL` → `u[IU]/mL` | `3016-3` | unchanged | — |

The two errors ran in **opposite directions**, so there is no single systematic transform and
a find-and-replace on a bare code introduces new defects: `14920-3` remains *correct* wherever
it is paired with `pmol/L` (as in the calibration, QC, and OUL fixtures and both profile JSONs).
LIS-299 added a property-compatibility regression rather than a string-presence assertion,
because the sim suite passed with both wrong mappings in place.

Two YAML binding traps are load-bearing in the bridge config and are documented in place:
codes with a literal `" II"` suffix and unit keys containing `/` **must** be bracket-indexed
(`"[FT4 II]"`, `"[uIU/mL]"`) or Spring silently fails to bind them.

### Everything else is synthetic seed

The remaining panel (AFP, CEA, …) ships deliberately unmapped or as synthetic seed and
graduates to real values as each assay is captured. Unmapped codes take the
PARTIAL/UNMAPPED review path and stage read-only "configuration needed" (LIS-272).

Modeling reference: `contexts/core-openelis/docs/adr/0002-loinc-ucum-vendor-code-seed.md`;
core tables `clinlims.vendor_code_mapping` / `test_terminology_mapping`.

## AC5 — raw archive and replay evidence

Source capture: `evidence/bench/maglumi-x3/20260717-0101010034012301113/`,
session `raw-20260717-144818-005.bin`
(sha256 `2c50acec48e69f8e24f1abadde11820e284c656a856e74e9a4fca01679900076`), decoded in
`annotated-20260717-144818-005.log`. MAGLUMI X3 SN `0101010034012301113`, captured
2026-07-17 with the chassis disconnected (a stored-result replay via the analyzer's own
`Result` tab → `LIS Online`), so the bytes are genuine firmware output.

The fixture `edge/sim/fixtures/snibelis-maglumi-x3-result-upload/` is anchored to that raw
capture by sha256 in its manifest. Every field — codes, units, ranges, flags, the R.13
completion timestamp — is verbatim; the fixture combines three separately-captured
single-assay envelopes into one multi-order transmission for test convenience.

Replay is deterministic and governed by
`docs/adr/0012-raw-message-archive-and-deterministic-replay.md`. Either replay path
reproduces the demo:

```
scripts/x3_astm_capture.py --replay <raw.bin> --to HOST:PORT [--gap N]
deploy/kit/scripts/prove-site-x3-e2e.sh          # X3_FIXTURE_FILE anchors to the checked-in bytes
```

Run evidence in `run/`:

- `prove-site-x3-e2e.log` — the wire → bridge → FHIR → staged leg, including the LIS-270
  blank-patient-identity assertion.
- `staged-analyzer-results.txt` — the staged rows as captured before acceptance.
- `final-results.txt` — the accepted final Result rows.

The replayed payload is 335 bytes, sha256
`baf92a3738bcd4bbed784c57fe8d8241268963e5306c192575c070266eb4adae`, cross-checked against
the checked-in `message.astm` via `X3_FIXTURE_FILE` so the run is anchored to source rather
than to an inlined constant.

## AC1 — normalized patient result reaches a final Result — MET

The signed fixture entered the deployed listener, was identified as the registered X3
channel by observed source IP, was forwarded as a FHIR bundle to `/analyzer/fhir`, staged as
three `analyzer_results` rows, and was then technically accepted into three final
`clinlims.result` rows. Staging was consumed (3 → 0) and the accept transaction created the
sample, sample item and analyses itself — the fixture's accession has no pre-existing order.

```
accession          | test                            | analysis_status      | value | raw_code
PATIENT-REDACTED-1 | Transaminases GPT (37°C)(Serum) | Technical Acceptance | 5.43  | FT3
PATIENT-REDACTED-1 | Transaminases G0T (37°C)(Serum) | Technical Acceptance | 1.58  | FT4 II
PATIENT-REDACTED-1 | Glucose(Plasma)                 | Technical Acceptance | 2.78  | TSH II
```

`Technical Acceptance` is the terminal state of the accept transaction itself. `Finalized`
follows only when the autoverification gate is enabled and clears the analysis, so the proof
asserts either state rather than `Finalized` alone.

Before this slice the deployed proof stopped at *staged* `analyzer_results`; the acceptance
leg is `deploy/kit/scripts/prove-site-x3-accept.sh`, added here.

## AC2 — raw evidence preserved, mappings populated — PARTIAL

Preserved verbatim through acceptance, asserted 3/3: raw code, raw unit, value, the
analyzer-reported reference range, and the abnormal flag. This is the LIS-97 contract
holding at the core boundary — these are distinct from the lab-owned `min_normal`/
`max_normal` limits, which the accept path leaves untouched.

Two gaps keep this from MET:

1. **The LOINCs demonstrated are not the bench dictionary's.** `prove-site-x3-e2e.sh`
   deliberately maps the three wire codes onto arbitrary catalog tests with distinct LOINCs
   and distinct display names — a deliberate choice to dodge the staged-results dedup
   collapse, but it means the run exercises `1742-6` / `1920-8` / `2345-7` (GPT/ALAT,
   GOT/ASAT, Glucose) rather than the bench dictionary's `14928-6` / `3024-7` / `3016-3`.
   **No accepted-result run in this record demonstrates the real X3 dictionary reaching
   OpenELIS.** Current core and deploy-kit pins now provide the versioned analyzer, tests,
   mappings, UOM/UCUM values, and an e2e proof that refuses proxy catalog mappings. Closing
   this gap requires a fresh `prove-site-x3-e2e.sh` → `prove-site-x3-accept.sh` run on those
   pins, not another implementation change.
2. **The historical run recorded blank UCUM for `ng/dL`.**
   `FhirBundleBuilder.toUcum` consults the per-analyzer resolver first and falls back to a
   hardcoded backstop; LIS-119 populated that backstop with `uIU/mL` and `pmol/L` but not
   `ng/dL`, FT4 II's bench-confirmed unit. The bridge's `configuration.yml` maps it, and the
   current versioned analyzer registry/seed supplies `ng/dL` at both raw-unit and
   canonical-UCUM axes. The fresh current-pin run above must replace this historical blank
   with the exact value before AC2 moves to MET.

## AC3 — QC routing — NOT MET

Not closable from this slice, and the reason is upstream of it. The active discriminator is
`FIELD_EQUALS O.12 == "Q"`, and **no bench capture has ever confirmed the X3 populates
`O.12` at all** — every captured patient O-record is `O|1|<id>||^^^CODE` with ~5 fields,
shorter than the field the rule targets. Replaying the synthetic QC fixture
(`edge/sim/fixtures/snibe-maglumi-x3-qc-astm/`) would demonstrate that the classifier
routes a payload carrying the marker; it would **not** demonstrate that the real analyzer
emits one, which is what this AC asks for. The proof is LIS-266 (chassis-attached QC
capture). Until then the guarded go-live posture and its required operator QC-review SOP
stand as the compensating control.

## Known caveats carried into this demo

These are recorded rather than fixed by this slice, and each is tracked separately.

- **The QC discriminator is not wire-proven (LIS-266).** The active rule is
  `FIELD_EQUALS O.12 == "Q"`, but no capture has ever confirmed the X3 populates `O.12` at
  all — every captured patient O-record is `O|1|<id>||^^^CODE` with ~5 fields, shorter than
  the targeted field. It ships **active** because guarded go-live requires QC provisioning to
  be present, but if the analyzer never emits `O.12` the rule silently never fires and QC rows
  fall into the patient stream undetected. The operator QC-review SOP
  (`docs/runbooks/x3-qc-guarded-go-live.md`) is a **required compensating control**, not
  optional guidance. Technical-owner authorization is recorded
  (`docs/compliance/sign-off/LIS-269-x3-guarded-go-live-authorization.md`, LIS-COMP-SIGNOFF-003);
  **independent QA sign-off remains open.** The `CALIBRATION_SPECIMEN_ID_PREFIX` rule ships
  inactive by design.
- **No patient identity on the wire (LIS-270 / LIS-296).** The X3 sends a bare `P|1` with no
  patient id or name, so `patientHint` must be left **blank** — there is nothing to populate it
  from. The LIS-239 duplicate guard is structurally inert on this analyzer. The staging UI shows
  a "No patient identity from analyzer" banner and the operator accept procedure in
  `docs/runbooks/x3-patient-identity-verification-sop.md` is a go-live gate; the systematic
  control is LIS-296, still open.
- **Order download is not implemented (LIS-177).** `direction: upload-only`. The demo shows the
  upload half only.
- **Idle-teardown defect (LIS-265).** A long-lived socket idling between envelopes can be severed
  with silent loss; reproducible with `--gap N`. Documented in
  `thoughts/lis-174-idle-timeout-issue-draft.md`, not yet fixed.
- **Auto-upload from a live run has never been captured (LIS-266).** Every capture to date is a
  manual `→ LIS Online` replay with the chassis disconnected.

## Reproducing this demo

From the umbrella checkout, with `core/openelis`, `edge/drivers` and `deploy/kit`
initialized (**including `core/openelis`'s own nested submodules — the image build fails on
a missing `dataexport` POM otherwise**):

```bash
export BRIDGE_AUTH_PASSWORD=... LIS_SITE_OE_USER=admin LIS_SITE_OE_PASSWORD=...
deploy/kit/scripts/compose-site.sh up          # builds both stacks from the pins, waits healthy
deploy/kit/scripts/prove-site-x3-e2e.sh        # wire -> bridge -> FHIR -> staged
deploy/kit/scripts/prove-site-x3-accept.sh     # staged -> accepted final Result
deploy/kit/scripts/compose-site.sh down
```

Set `X3_FIXTURE_FILE=edge/sim/fixtures/snibelis-maglumi-x3-result-upload/message.astm` to
anchor the replay against the checked-in bytes.

Operational notes learned running it:

- `compose-site.sh up` refuses to run from a linked git worktree, since deployed config and
  state binds point at a checkout that worktrees treat as disposable. Override with
  `LIS_DEPLOY_ALLOW_WORKTREE=true` for a proof stack, and **`down` the stack before removing
  the worktree**.
- The acceptance proof is **not idempotent across acceptance**. In the current proof,
  `CLEAN=true` on `prove-site-x3-e2e.sh` deletes only proof-accession staged rows and
  preserves the migration-owned analyzer/Test/map/UOM/QC seed. If the accession already has
  accepted finals, `prove-site-x3-accept.sh` detects them before POST and fails closed because
  it cannot distinguish a new result from stale evidence. Recreate the proof stack before
  rerunning the acceptance leg.
- Do not delete that graph by hand in psql. Deleting `sample_human` without its `sample`
  leaves an orphaned sample, and the analyzer-results worklist then throws an NPE
  (`StatusService.setRecordStatus`, `sampleHuman` null) which the REST controller swallows
  into an empty `resultList` — the worklist silently reports "no results found" while rows
  sit staged. Recreating the stack is the reliable reset.
