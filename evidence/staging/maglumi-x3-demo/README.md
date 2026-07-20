# MAGLUMI X3 staging end-to-end demo — LIS-39

Demonstration of the SNIBE MAGLUMI X3 native Online ASTM channel deployed as a site
stack (pinned OpenELIS core + pinned analyzer bridge) and driven end to end with the
LIS-75 bench-graduated fixture. No SnibeLis middleware is present anywhere on the path:
the X3 speaks ASTM E1394-97 directly to the bridge, which forwards FHIR to OpenELIS.

**Status: IN PROGRESS.** Configuration and mapping sections (AC4, AC6) are complete and
were read from the pinned sources cited below. The run sections (AC1, AC2, AC3, AC5) are
filled in from the demo execution and are marked `PENDING` until that run is recorded.

## Pinned versions under demonstration

The "mapping profile version" this demo records is the git pin — there is no separate
`profileVersion` key in the X3 profile. Each artifact below is pinned by SHA in the
umbrella at the commit that carries this record.

| Component | Path | Pin |
|---|---|---|
| OpenELIS core | `core/openelis` | `25e06ea4a1f7ba25896e176b87b546ff87e4bbcc` |
| Analyzer bridge | `edge/drivers` | `46e57b9fc631d727eb977b2740de119b9343c04f` |
| Deploy kit | `deploy/kit` | `579aacb415635c74034a87245f3597f733a096a8` |

Mapping-profile sources at those pins:

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

Run evidence: **PENDING** — see `run/` in this directory.

## AC1 / AC2 — normalized patient result

**PENDING.**

## AC3 — QC routing

**PENDING.** Note the standing constraint recorded below.

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
