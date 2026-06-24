# ADR-0002 — Deployment topology: fully-onsite pilot, on-prem central-sync as a post-pilot spoke

- **Status:** Accepted
- **Date:** 2026-06-24
- **Deciders:** Marloe Uy (System owner), Artis Lindy Pinote (QA/regulatory owner)
- **Supersedes / Superseded by:** —
- **Resolves:** Open Decision #3 (deployment topology) in `LIS_IMPLEMENTATION_PLAN.md` §6 /
  `LIS_BUILD_AND_INTEGRATION_RESEARCH.md` §13; **DEC-03** in `docs/compliance/decisions-register.md`.

## Context

The LabSolution LIS (a fork of OpenELIS Global 2 plus a LabSolution-owned instrument
driver/analyzer-bridge edge layer) is sold to DOH-licensed clinical laboratories and
hospitals in the Philippines. How PHI is deployed and whether it ever leaves a customer
lab was the single load-bearing **compliance** decision, not merely an architecture one:
the topology sets LabSolution's RA 10173 PIC-vs-PIP status, its NPC registration duty, its
breach apparatus, its cross-border exposure, and its physical-custody obligations
(`docs/compliance/responsibility-and-deployment.md`).

Three models were analyzed (see that note for the full requirement-by-requirement split):

- **M1 — fully onsite.** The LIS runs entirely on-premises at each lab; no sync; LabSolution
  ships software and, by default, never accesses or stores PHI. LabSolution is **neither PIC
  nor PIP** (a software supplier outside the RA 10173 processor taxonomy), subject to the
  load-bearing premise that no support/telemetry/backup channel actually touches live PHI.
  Smallest attack surface; lowest vendor compliance burden.
- **M2 — onsite + public-cloud sync.** PHI replicates to a public-cloud service (possibly
  offshore). LabSolution becomes a **PIP**; introduces the genuine cross-border model, the
  longest sub-processor flow-down chain, and the highest vendor compliance burden.
- **M3 — onsite + central sync at LabSolution's own on-prem datacenter, in PH.** PHI
  aggregates to a central node LabSolution operates on its own PH premises. LabSolution
  becomes a **PIP with physical custody**: purely domestic (no cross-border), shortest
  sub-processor chain, but the heaviest NPC Circular 2023-06 **physical-security / BCP /
  key-custody** duties.

On vendor compliance burden the analysis ranked them **M1 < M3 < M2**.

The programme needs a validated single-site pilot first; the cross-site aggregation/sync
capability is a later, separable feature.

## Decision

1. **The pilot deploys on M1 — fully onsite, per site, no sync.** Each pilot lab runs the
   LIS entirely on its own premises; PHI never leaves the lab. This is the **committed
   topology for Stage 5 validation and pilot go-live**. The pilot's IQ/OQ/PQ dossier,
   threat model, and NPC posture are scoped to M1 only.

2. **The central-sync capability is M3 — LabSolution's own on-prem datacenter, in PH — and
   is a POST-PILOT additional spoke.** Public-cloud sync (M2) is **not** the chosen sync
   path. When cross-site aggregation is built, it terminates on LabSolution-controlled
   infrastructure located in the Philippines.

3. **The pilot does not depend on the sync/M3 work.** The store-and-forward sync service,
   the central node, and all M2/M3-specific compliance are **decoupled** from the pilot
   critical path. The pilot can ship and go live with zero sync code and zero
   PIP-status compliance.

4. **A "compliance extra work" gate precedes the M3 spoke.** Before the on-prem
   central-sync spoke is implemented, the M3 PIP obligations enumerated in
   `docs/compliance/m3-sync-compliance-gate.md` must be completed (LabSolution registers
   its own aggregation DPS, stands up its own breach apparatus, designs central key custody
   and the datacenter physical-security/BCP controls, executes the head DPA + middleware
   flow-down, and re-runs the threat model and PIA). Building the M3 spoke is itself a
   change-control / revalidation **delta on the M1 known base** (REQ-QMS-03), not a
   re-validation from zero.

5. **M2 (public cloud) is retained as a considered, NOT-selected alternative.** Its
   analysis stays in `responsibility-and-deployment.md` for the record and in case a future
   customer specifically requires cloud residency; it is off the active roadmap and out of
   the pilot/spoke scope.

The committed roadmap is therefore:

```
M1 (pilot — committed, no sync)
        → [ compliance extra work gate — m3-sync-compliance-gate.md ]
                → M3 (own on-prem central-sync spoke, post-pilot)

M2 (public cloud) — considered, NOT selected (parked)
```

## Consequences

**Positive**
- **Pilot compliance burden is the lowest of the three models.** In M1 LabSolution is a
  software supplier: its only direct duties are its product QMS, license hygiene, an FDA
  SaMD manufacturer registration *if* the autoverification layer qualifies, and its own
  corporate NPC filing — **no PHI-custody, NPC sync-DPS registration, breach, or
  cross-border duty over the lab's data.** This shortens the path to pilot go-live.
- **Smallest pilot attack surface.** No sync boundary (threat boundary TB-5 does not exist
  in the pilot) and at-rest PHI (TB-7) lives only inside each lab's perimeter.
- **The sync feature is de-risked and unblocked from the pilot.** It can be designed in
  parallel and shipped later without holding up validation.
- **Clean validation story.** M1 is the known base; M3 is a delta validated on top of it
  under change control — exactly the "deltas on a known base" model the VMP relies on.

**Negative / costs**
- **The M3 spoke carries a real, deferred compliance cost** — LabSolution becomes a PIP
  with physical custody and inherits the heaviest NPC Circular 2023-06 physical-security,
  BCP, breach-apparatus, and key-custody duties. The `m3-sync-compliance-gate.md` checklist
  makes that cost explicit and gates the spoke so it cannot be built ahead of the paperwork.
- **The M1 "neither PIC nor PIP" conclusion is fact-dependent** (DEC-17 / the vendor-PHI
  boundary): it holds only if no remote-support session, telemetry, crash dump, log, backup,
  update channel, or offshore staff access actually touches live PHI. This must be confirmed
  with engineering and counsel, and any residual access locked down with a scoped support
  DPA + break-glass controls — **even for the M1 pilot.**

**Load-bearing caveats (carried from the responsibility note; confirm before relied on)**
- The M1 characterization and the FDA SaMD classification turn on facts engineering and PH
  privacy/health-regulatory counsel must verify. This ADR records an internal architecture
  + compliance-scope decision; it is **not** legal advice.

## Alternatives considered

- **M2 — public-cloud sync (offshore or in-PH region):** rejected as the chosen sync path.
  It maximizes vendor compliance burden (PIP status, own DPS registration, own breach
  apparatus, the longest sub-processor flow-down chain, and offshore cross-border
  accountability) and adds a third-party cloud trust boundary. Retained only as a parked
  alternative for a future customer that explicitly requires cloud residency. *(For
  public-hospital/government customers an offshore M2 may also be foreclosed if the DICT
  government data-residency draft is finalized.)*
- **M3 from day one (sync in the pilot):** rejected — it would pull the full PIP-status
  compliance gate onto the pilot critical path and enlarge the pilot threat surface for a
  capability the pilot does not need.
- **One global topology for all customers:** the responsibility note recommends a
  per-customer decision gate (esp. public-vs-private customer). This ADR fixes M1 as the
  default and pilot topology and M3 as the default sync spoke; a specific customer's
  requirement can still be revisited as its own decision.

## References

- `docs/compliance/responsibility-and-deployment.md` — requirement-by-requirement PIC/PIP
  split and the M1/M2/M3 comparison this decision rests on.
- `docs/compliance/m3-sync-compliance-gate.md` — the compliance extra-work checklist gating
  the M3 spoke.
- `docs/compliance/validation-master-plan-outline.md` §12 — stage-gated schedule (pilot = M1;
  M3 as a post-pilot revalidation delta).
- `docs/compliance/decisions-register.md` — DEC-03 (now resolved by this ADR).
- ADR-0001 — pinned-submodule snapshot = the reproducibility / IQ spine the delta-validation
  model depends on.
