# LIS diagrams

Eight Excalidraw diagrams accompanying `../LIS_BUILD_AND_INTEGRATION_RESEARCH.md`
and `../LIS_IMPLEMENTATION_PLAN.md`.

## Files

| File | What it shows |
|---|---|
| `01-reference-architecture.excalidraw` | Edge → interface engine → normalization → OpenELIS core → FHIR, with cross-cutting compliance; distinguishes in-pilot single-site edge store-and-forward (M1) from the post-pilot site↔central sync (M3 spoke) |
| `02-implementation-roadmap.excalidraw` | Stages 0–6 + the post-pilot M3 central-sync spoke in three lanes (deliverable / red verify-gate / milestone MS1–MS7), G0–G6 stage gates; G5 = the compliance extra-work gate before the spoke |
| `03-fleet-protocol-map.excalidraw` | Fleet grouped by protocol, ordered clean-HL7-first → proprietary-last (HORRON verify flag) |
| `04-message-exchange-sequence.excalidraw` | HL7 v2 + ASTM handshake: host-query / order-down, result-up, ACK |
| `05-offline-sync-topology.excalidraw` | The **post-pilot M3 spoke** (ADR-0006): site (validated M1 base) ↔ LabSolution's own on-prem datacenter in PH (not public cloud); store-and-forward, append-only result versions, explicit reconciliation; gated by the compliance extra-work — not in the pilot |
| `06-regulatory-controls-map.excalidraw` | 6 regimes → 12 LIS controls; sprint-1 hard-reqs outlined in red; side panel = RA 10173 PIC/PIP split by topology (M1 lab=PIC, LabSolution neither; M3 LabSolution=PIP) |
| `07-er-data-model.excalidraw` | Dual-coded Result (raw + LOINC/UCUM), host-query Worklist, append-only AuditEvent |
| `08-verification-pyramid.excalidraw` | Unit → bench conformance → integration E2E → IQ/OQ/PQ, mapped to roadmap gates |

## How to open / edit

Any of:
- **[excalidraw.com](https://excalidraw.com)** → *Open* (or drag-and-drop the file)
- **Excalidraw desktop app**
- **VS Code** with the *Excalidraw* extension (open the `.excalidraw` file directly)

## Regenerate

The `.excalidraw` files are generated from the compact scene sources in `_src/`.
Edit a source and rebuild:

```bash
python3 build.py
```

`build.py` expands `label` shorthands into bound text, drops camera markers, and
fills the Excalidraw element fields. No third-party dependencies (stdlib only).
Style: clean `roughness: 0`, proportional font; the sequence diagram carries a
real MLLP-framed HL7 v2.3 `ORU^R01` evidence artifact.

## Previews

A `.png` sits next to each `.excalidraw` — render previews produced with the
`excalidraw-diagram` skill's Playwright renderer
(`.claude/skills/excalidraw-diagram/references/render_excalidraw.py`). Regenerate
a preview after editing:

```bash
cd .claude/skills/excalidraw-diagram/references
uv run python render_excalidraw.py /home/marloeu/projects/lis-control-lis-10/diagrams/<name>.excalidraw
```
