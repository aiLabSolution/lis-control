# SOP — verifying patient identity for analyzers that send none (SNIBE MAGLUMI X3)

Operator standard operating procedure for accepting analyzer results on channels
whose wire carries **no patient identity**. Written for LIS-270; the first such
channel is the **SNIBE MAGLUMI X3** native ASTM `Online` interface, which sends a
bare `P|1` patient record — no patient id, no name.

**Audience:** the laboratory technician who reviews and accepts analyzer results
in the OpenELIS *Analyzer Results* staging worklist. **This is a manual control.**
It is the primary defence against a wrong-patient result on these channels until
the systematic control ([scheduled follow-up](#residual-risk-after-this-sop)) ships.

## Why this SOP exists (the residual risk)

OpenELIS matches an inbound analyzer result to a patient **only** through the
accession number the analyzer reports. On most wires a second signal — the
**wire patient identity** (e.g. HL7 PID-2, forwarded by the bridge as a
`patientHint`) — lets the software catch a same-day collision where two different
patients' results arrive under one accession (the LIS-239 guard).

**The X3 wire carries no such signal.** Every X3 result stages with a blank
patient hint, so the LIS-239 same-day patient-mismatch guard is **structurally
inert** on this channel: it cannot fire. Consequence — if an operator mis-keys or
mis-scans a sample ID at the analyzer so it collides with **another same-day
patient's** accession, the X3 result attaches to the **wrong patient**, and no
downstream software check on this wire will catch it.

On this channel, the accession the operator enters at the analyzer, and the
operator's review at accept, are the only defences against a wrong-patient attach.

## How to recognise an affected worklist

The staging worklist raises a prominent warning banner at the top:

> **No patient identity from analyzer** — These results carry no patient identity
> on the wire. Confirm each accession number matches the intended patient before
> accepting …

The banner appears whenever any patient row on the worklist came in without a
wire patient identity (it is suppressed for QC control rows, which have no
patient dimension). Treat its presence as the trigger for the procedure below.

## What the software still catches — and what it does NOT

Already enforced (do **not** rely on these to catch a wrong-patient mis-key):

- **LIS-158** — a linked correction pair never commits silently; the technician
  must explicitly USE or DISMISS, and both values are audit-noted.
- **LIS-126** — an accession that maps to **no** registered sample/patient
  requires an explicit "accept as unidentified patient" confirmation.
- **LIS-128** — a linked pair completing on **different calendar days**
  (reused-accession signature) refuses USE, fail-closed.
- **LIS-239** — a linked pair carrying **two different non-blank** wire patient
  identities refuses USE, fail-closed.

**Not caught on the X3 wire** (this is the residual this SOP mitigates): a
same-day result that attaches to a **valid but wrong** patient's accession,
because there is no wire patient identity to compare and the accession itself
resolves cleanly. LIS-239 needs a non-blank hint on both rows; the X3 never
sends one.

## The procedure

When the *No patient identity from analyzer* banner is shown, **before** ticking
Accept on any row:

1. **Read the accession number on each row** (the *Sample Info* column). Do not
   bulk-accept the worklist blind.
2. **For each accession, confirm it belongs to the patient the sample was drawn
   from.** Cross-check against the physical sample label / worklist / order the
   sample was run under at the analyzer — not against whatever patient the
   accession happens to resolve to in OpenELIS (that is the value you are
   verifying, not the source of truth).
3. **If an accession does not match, do not accept it.** Reject the row (Retest)
   or ignore it, quarantine the physical sample, and follow local
   incident-reporting for a suspected sample-ID mismatch. Re-run under the
   correct accession.
4. **Only then** accept the rows whose accession you have confirmed.
5. Where the sample was a walk-up / unregistered accession, the LIS-126
   confirmation still applies **in addition** to this check.

## Residual risk after this SOP

This SOP is a **manual, operator-dependent** control. It does not remove the
residual — it makes it visible and assigns a procedure. Go-live on the X3
channel is gated on this SOP plus the staging-UI banner (LIS-270).

The **systematic** control — an order-side cross-check that holds, for review, an
analyzer result reporting a test that was never ordered on the resolved accession
— is tracked as scheduled follow-up slice **LIS-296**. That control fires only on
the anomalous case (no habituation) and does not depend on the operator, but it
is a larger, all-analyzer change and still cannot catch a collision where both
patients legitimately ordered the same test.

## References

- **LIS-270** — this residual and the go-live gate (banner + SOP + follow-up).
- **LIS-239** — the same-day patient-mismatch guard that is inert on this wire.
- **LIS-126 / LIS-128 / LIS-158** — the accept-boundary controls listed above.
- Bench evidence that the X3 sends a bare `P|1`: `docs/runbooks/snibe-maglumi-x3-bench.md`
  and the annotated captures under `evidence/bench/maglumi-x3/`.
- Staging-UI signal source: `core/openelis` — the *Analyzer Results* worklist
  (`frontend/src/components/analyserResults/AnalyserResults.jsx`) driven by the
  server-computed `wirePatientIdentityAbsent` flag
  (`result/controller/AnalyzerResultsController.java`).
