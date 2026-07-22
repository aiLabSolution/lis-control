# Conformance fixtures

Each fixture is a directory containing a `manifest.json` and the raw message bytes
it references. Manifests are validated against
[`schema/fixture.schema.json`](schema/fixture.schema.json) — the single,
language-neutral source of truth for the contract.

A fixture is **evidence** in the ISO 15189 traceability chain (requirement → test →
evidence): the `source` block records provenance, and `synthetic` flags whether the
message is a real instrument capture.

## Manifest fields

| Field | Required | Notes |
|---|---|---|
| `id` | ✓ | Stable kebab-case id, unique across the tree. |
| `description` | | What the message exercises. |
| `analyzer.vendor` / `analyzer.model` | ✓ | The instrument. |
| `protocol` | ✓ | `hl7v2` \| `astm-e1394` \| `astm-e1381` \| `raw`. |
| `transport` | ✓ | `mllp` \| `serial-rs232` \| `astm-tcp` \| `file` \| `loopback` — the real wire; the harness replays via a matching `Transport` or protocol-specific session simulator. |
| `direction` | ✓ | `analyzer-to-host` \| `host-to-analyzer` \| `bidirectional`. |
| `message.path` | ✓ | Raw **application-payload** bytes file (no wire framing). |
| `message.encoding` | ✓ | `ascii` \| `latin-1` \| `utf-8`. |
| `message.framing` | ✓ | `raw` \| `mllp` \| `astm` \| `snibelis-astm` — framing the transport applies/strips. |
| `source.reference` | ✓ | Manual section, capture-session id, or synthetic-seed note. |
| `source.captured_at` / `source.note` | | Provenance detail. |
| `synthetic` | ✓ | `true` = illustrative/seed; real captures set `false`. |
| `expected` | | Placeholder for downstream parser/normalization assertions (LOINC/UCUM Result), wired up in Stage 1. |

## Why payload-only (no wire framing)?

The fixture stores the **application message** (e.g. the HL7 segments), not the wire
envelope. MLLP's `0x0B … 0x1C 0x0D` and ASTM's checksummed frames are a *transport*
concern, applied at replay time by the matching `Transport`. This keeps one captured
message reusable across transports and keeps the conformance artifact stable as
framing codecs land in later slices.

## Seeds

`_example/` is a **synthetic** HL7 v2.3 `ORU^R01` (LOINC 718-7 Hemoglobin, UCUM
`g/dL`). It exists so the replay self-test has something to chew on before real
captures arrive. Real RAYTO RAC-050 and Mindray labXpert captures land in Stage 1.
`snibelis-maglumi-x3-*` are synthetic seeds for the SnibeLis/MAGLUMI X3 ASTM E1394
path: `-query-request` / `-result-upload` are the LIS-108 session and query seeds,
the latter extended by LIS-32 with the immunoassay LOINC/UCUM normalization contract
(TSH, FT4); `-result-unmapped` is the LIS-32 seed proving unknown assays/units are
flagged (PARTIAL/UNMAPPED) rather than dropped. Their terminology tables are minimal,
NOT site-verified — replace them with real SnibeLis captures after the LIS-75
middleware/license gate opens (graduated by LIS-38).

## Capture intake and sanitization (quarantine-first)

Bench captures carry PHI — the MAGLUMI X3's ASTM O-record field 3 (the
specimen/sample-id position) has carried a real patient name (see
`evidence/bench/maglumi-x3/20260717-0101010034012301113/`). Intake is
quarantine-first: a raw bench capture (`raw-*.bin` + its `annotated-*.log`
companion from `scripts/x3_astm_capture.py`) lands in a quarantine directory
**outside** this repository and never goes straight into a PR.

`edge-sim sanitize` (`edge_sim.sanitize`, LIS-319) redacts one addressed ASTM
field across every envelope of a quarantined capture (plus its annotated log,
if given), verifies in memory that the sanitized capture is structurally
identical to the original before writing anything, and produces:

* the sanitized capture (+ log), with every occurrence of the addressed
  field replaced by the same canonical token;
* a `sanitization.json` transformation ledger recording *that* a redaction
  happened — deliberately never the original value, its length, or an
  absolute path.

A named human privacy review must be recorded in the ledger
(`review.privacy_reviewed_by` + `review.reviewed_at`, both `null` until then)
before any fixture-graduation PR may include the sanitized artifact.
Graduation tooling refuses an unreviewed ledger — that enforcement lands with
the graduation slice, LIS-276.

## Canonical redaction tokens

`edge_sim.sanitize.TOKEN_CLASSES` is the canonical vocabulary a redaction's
`--class` selects from (the default token is the class prefix + `--ordinal`,
e.g. `PATIENT-REDACTED-1`; an explicit `--token` overrides it):

| Class | Token prefix |
|---|---|
| `patient-name` | `PATIENT-REDACTED-` |
| `operator-id` | `OPERATOR-REDACTED-` |
| `specimen-id` | `SPECIMEN-REDACTED-` |

`BENCH-SAMPLE-001` is **legacy/grandfathered**: it was hand-applied to the
2026-07-17 session 004 evidence before this tool existed
(`edge_sim.sanitize.LEGACY_TOKENS`) and stays recognized in that evidence —
`edge-sim sanitize` never emits it for a new redaction.

Re-synthesis of measurement content (values, ranges and result timestamps, as
opposed to identifier redaction; units and assay codes are preserved verbatim)
is a ratified decision but must **not** be performed
until the shape-preserving derivation spec exists — see `DERIVATION.md` in
this directory (filed in this same slice) and plan §17.3.1.
