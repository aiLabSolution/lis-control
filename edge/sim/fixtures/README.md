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
`snibelis-maglumi-x3-*` are synthetic LIS-108 seeds for the SnibeLis/MAGLUMI X3
ASTM E1394 session and query path; replace them with real SnibeLis captures after
the LIS-75 middleware/license gate opens.
