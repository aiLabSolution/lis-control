# ADR-0019 — QC-acceptance responsibility allocation (never auto-accept; engineer sign-off owned by OpenELIS core)

- **Status:** Proposed — **pending QA/regulatory owner (Pinote) sign-off** to become Accepted (safety-critical, see below)
- **Date:** 2026-07-08
- **Deciders:** Marloe Uy (System / technical owner — proposer); Artis Lindy Pinote (Functional + QA/regulatory owner — **sign-off required**)
- **Supersedes / Superseded by:** —
- **Depends on / relates to:** ADR-0007 (regulatory ownership & responsibility allocation — this ADR
  allocates one specific safety-critical obligation under that baseline); ADR-0015 (edge transport
  substrate & channel attachment — the edge/bridge whose obligation this ADR bounds); ADR-0013
  (Stage-1 milestone e2e & ingest-contract correspondence — the ingest seam QC is kept out of).
- **Resolves:** the **AC4 disposition of LIS-33** ("QC acceptance requires engineer sign-off; nothing
  auto-accepted") and the equivalent gate wording carried by sibling analyzer-QC slices (LIS-125
  calibration gate lineage; LIS-95 MSH-16 QC/cal routing).

## Context

Analyzer QC results are safety-critical: a QC value must **never** be auto-accepted as if it were a
released patient result, and its acceptance/rejection must pass an engineer's review (the
"never auto-accept QC / engineer sign-off" rule). Several slices name this obligation verbatim as an
acceptance criterion — most recently **LIS-33** ("[S3.2] X3 QC results classified host-side, kept out
of the patient stream"), whose AC4 is exactly this gate.

The question this ADR settles is **where that gate lives**, because the obligation spans three layers:

1. **The edge/bridge** (`edge/drivers`, ADR-0015) — receives the analyzer wire, *classifies* QC out of
   the patient result stream (ASTM O.12=Q or a versioned QC Sample-ID convention; HL7 SPM-11 role Q /
   MSH-16=2), and tags it (`qc/lot-number`, `qc/control-level`, a `QC` meta tag) on the FHIR bundle.
2. **The edge/sim** (`edge/sim`, ADR-0004) — the conformance mirror that proves the classification/
   stream-routing contract against fixtures.
3. **OpenELIS core** (`core/openelis`) — owns the QC-verification module (Westgard/LJ machinery is
   upstream; QC review UI + `QCResultProcessingService`), i.e. the actual **acceptance/sign-off
   workflow** where an engineer accepts or rejects a control run.

During the LIS-33 review it was confirmed that:

- The edge/bridge **classifies and tags** QC correctly and emits QC observations with a **non-final
  (`PRELIMINARY`) FHIR status** (`FhirBundleBuilder` DiagnosticReport/Observation status), so a QC row
  cannot land in the append-only Result store as an authoritative, auto-accepted result.
- The edge/sim proves **stream classification** (QC re-kinded to `KIND_QC`, zero patient `KIND_RESULT`
  rows, excluded from `ingest_payload`) — it does **not**, and structurally cannot, host an
  acceptance/sign-off workflow.
- There is **no auto-accept-prevention code, and no acceptance/sign-off gate, in the edge at all** — nor
  should there be. The engineer-sign-off workflow is an OpenELIS-core QC-module responsibility that
  pre-dates this venture's edge work.

Leaving AC4 phrased as an *edge* obligation makes it perpetually "unmet" against edge code and invites
the "Done with an unmet named AC" failure mode this project has repeatedly hit — when in fact the edge's
whole obligation (classify out of the patient stream + tag + emit non-final) is met, and the sign-off
obligation is met by a different, already-existing subsystem.

## Decision

**Allocate the QC-acceptance obligation across the layers, and re-scope the analyzer-slice AC wording to
match:**

1. **Edge/bridge obligation (met):** classify QC out of the patient result stream, tag it
   (`qc/lot-number`, `qc/control-level`, `QC` meta), and emit it **non-final (`PRELIMINARY`)** so it is
   never handed to core as an authoritative/auto-accepted patient result. The edge **surfaces** QC for
   review; it does **not** accept it.

2. **Edge/sim obligation (met, bounded):** assert **stream classification** only — QC is re-kinded out
   of the patient `KIND_RESULT` stream and excluded from the ingest payload. The sim mirror is **not**
   required to carry QC lot/control-level nor to model acceptance/sign-off; that tagging is asserted on
   the **bridge** side (FHIR extensions), and acceptance is a core concern.

3. **OpenELIS-core obligation (owner of the safety gate):** the **never-auto-accept / engineer-sign-off**
   acceptance workflow is owned by the OpenELIS-core QC-verification module. QC control runs are held for
   engineer review and accepted/rejected there; nothing on the edge auto-accepts.

4. **AC re-scope (applies to LIS-33 AC4, and the equivalent gate on sibling QC slices):** the acceptance
   criterion is met when (a) the edge classifies + tags + emits non-final QC, and (b) the sign-off gate
   is **delegated to the OpenELIS-core QC module** per this ADR. An analyzer slice does **not** carry an
   in-edge auto-accept-prevention test as its close gate; the delegation recorded here is the close gate,
   plus — where a slice wants defense-in-depth evidence — a bridge test asserting QC `Observation.status
   == PRELIMINARY`.

5. **Safety-critical sign-off:** because this reallocates a safety-critical obligation, this ADR is
   **Proposed** until the QA/regulatory owner (**Pinote**, DEC-01 / ADR-0007) signs off. Until sign-off,
   LIS-33 (and siblings gated on this wording) stay **out of Done** on AC4.

## Consequences

**Positive**
- **Unblocks LIS-33 (and the QC-gate wording on sibling slices) from a false "unmet AC".** The edge's
  real obligation is met and verifiable; the sign-off obligation resolves to a named, existing subsystem.
- **One clear home for the safety gate** — OpenELIS-core QC verification — with the edge's role bounded to
  classify + tag + non-final, which is exactly what it can prove.
- **Traceable delegation.** The `LIS-NN AC4 → ADR-0019 → OE-core QC module` chain is auditable for the ISO
  story, rather than a checkbox that never truthfully closes.

**Negative / residual `[NEEDS-HUMAN]`**
- **Requires QA/regulatory owner sign-off** before it is relied on; this is a reasoned allocation, not yet
  an approved one. It records an internal decision; it is not a validation record on its own.
- **The OE-core no-auto-accept behavior is asserted, not yet verified here.** A follow-up should add a
  core-side test proving QC control runs are held for engineer review and not auto-accepted, and (defense
  in depth) a bridge test asserting QC observations are `PRELIMINARY`. Until then the core half rests on
  documented, but untested-in-this-repo, behavior.

## Alternatives considered

- **Keep AC4 as an edge obligation and add an in-edge auto-accept-prevention gate.** Rejected: the edge
  has no acceptance workflow to gate; adding one would duplicate (and risk diverging from) the OE-core QC
  module that already owns acceptance, and would not reflect where the safety responsibility actually
  lives.
- **Amend ADR-0007 in place** to add the QC-acceptance clause. Rejected in favor of a new, narrowly-scoped
  ADR: ADR-0007 is an Accepted regulatory-ownership baseline; a discrete safety-gate allocation is easier
  to sign off and trace as its own record (this ADR references ADR-0007 as the governing baseline).
- **Close LIS-33 as Done now on the strength of the bridge `PRELIMINARY` status alone.** Rejected: a
  safety-critical gate should not silently ride an untested assumption; the delegation is recorded and
  signed off first, with the verifying test tracked as follow-up.

## References

- ADR-0007 — regulatory ownership & responsibility allocation (the governing baseline; QA/regulatory owner = Pinote).
- ADR-0015 — edge transport substrate & channel attachment (the edge/bridge whose obligation this bounds).
- ADR-0013 — Stage-1 milestone e2e & ingest-contract correspondence (the ingest seam QC is kept out of).
- ADR-0004 — analyzer-simulator harness & conformance fixtures (the edge/sim mirror's scope).
- LIS-33 — [S3.2] X3 QC results classified host-side, kept out of the patient stream (AC4 resolved here).
- LIS-95 — MSH-16 QC/cal routing (the HL7 QC-stream half, tracked separately).
