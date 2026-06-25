# ADR-0007 — Regulatory ownership & responsibility allocation

- **Status:** Accepted
- **Date:** 2026-06-25
- **Deciders:** Marloe Uy (System / technical owner), Artis Lindy Pinote (Functional + QA/regulatory owner)
- **Supersedes / Superseded by:** —
- **Resolves:** **DEC-01** (regulatory ownership), **DEC-02** (DPO appointment), **DEC-07**
  (named signatories) in `docs/compliance/decisions-register.md`; Open Decision #5
  (regulatory ownership) in `LIS_IMPLEMENTATION_PLAN.md` §6 / `LIS_BUILD_AND_INTEGRATION_RESEARCH.md` §13.
- **Depends on / relates to:** ADR-0006 (deployment topology — fixes which model drives the
  PIC/PIP split); `docs/compliance/responsibility-and-deployment.md` (the requirement-by-requirement
  allocation this ADR adopts).

## Context

DEC-01 ("regulatory ownership") was the single most-blocking item in the compliance scaffold:
until it was taken, **no signature line in the VMP, no Owner cell in the NPC checklist or
traceability matrix, and no `REQ-PRIV-*` / `REQ-VAL-01` row could be owned or closed**, and it
gated the DPO appointment (DEC-02), the named signatories (DEC-07), and the disposition of
HOLD-001 (DEC-08, see ADR-0008).

On inspection DEC-01 is really **two** decisions:

1. **The allocation** — *who is the legally responsible party* for each obligation. This is
   already answered, requirement by requirement, in
   `docs/compliance/responsibility-and-deployment.md` §2–§3 (grounded and cited): the customer
   lab/hospital is the **PIC** in all models; LabSolution is **neither PIC nor PIP in M1** (a
   software supplier outside the RA 10173 processor taxonomy) and a **PIP in M3**; the FDA SaMD
   *manufacturer* duty, if the autoverification/CDS layer qualifies the product as a medical
   device, sits on LabSolution **regardless of topology**. This part needed *adoption*, not
   invention.
2. **The appointment** — *who inside the venture is the named accountable owner*. This was the
   genuine open gap that every "DEC-01 owner" cell hangs off. ADR-0006 already implicitly named
   the people (its deciders are "Marloe Uy (System owner), Artis Lindy Pinote (QA/regulatory
   owner)"); this ADR makes that explicit and assigns the dependent roles.

**Legal-entity note (decided here).** The venture plans to stand up a child company to build
the LIS in-house (LabSolution historically *buys* LIS software from third parties; it is itself
a diagnostics-machine provider). For the purposes of this compliance scaffold, **LabSolution and
the planned LIS child company are treated as a single legal entity** — the one "LabSolution"
software-vendor / FDA-SaMD-legal-manufacturer of record. The `responsibility-and-deployment.md`
analysis therefore stands as written; there is **no** two-hop NewCo→LabSolution→lab processing
chain to model. (If the entities are later separated, this allocation must be re-pinned to the
actual vendor entity.)

## Decision

1. **Adopt the documented PIC/PIP allocation as the compliance baseline.** The customer
   lab/hospital is the **PIC** and bears primary, non-delegable RA 10173 accountability (Sec. 21)
   in all models; LabSolution (single entity, per the note above) is **neither PIC nor PIP at the
   M1 pilot** and a **PIP at the M3 spoke**; the **FDA SaMD manufacturer** duty is topology-invariant
   and sits on LabSolution if triggered; **per-customer labs own their own RA 4688 LTO** and
   on-site ISO 15189 Cl. 7.6 validation (LabSolution *enables*, it does not own these). This
   baseline is **subject to PH privacy/health-regulatory counsel confirmation** of the
   load-bearing characterizations (see §Structure).

2. **Named accountable owner (DEC-01).** **Artis Lindy Pinote** is the single accountable
   **QA/regulatory owner** — the canonical "DEC-01 owner" — accountable for the product-side ISO
   15189:2022 validation dossier (REQ-VAL-01), the product-side NPC corporate filing
   (REQ-PRIV-01 vendor part), the FDA SaMD classification call (REQ-REG-01), and every downstream
   Owner cell that names the "DEC-01 owner". **Marloe Uy** is the **system / technical owner**.

3. **Ownership structure: internal ownership + a scoped counsel retainer (DEC-01 option a, not c).**
   Pinote owns the validation dossier and the product-side NPC filing **end-to-end and accountably
   in-house**. External **PH privacy/health-regulatory counsel is retained on a narrow, defined
   scope to confirm (not own)** the load-bearing legal calls: the M1 "neither PIC nor PIP"
   characterization (via an **NPC advisory-opinion request** — the authoritative route), the FDA
   SaMD classification (via an FDA pre-submission), and the verbatim NPC Circular 2023-06 /
   breach-window / ISO 15189 clause confirmations (DEC-12/19/20). Ownership stays internal; only
   specialized legal *confirmation* is bought in.

4. **DPO appointment (DEC-02).** **Kirsten Pinote** is designated **Data Protection Officer**,
   reporting into the accountable owner. A DPO is required even at the M1 pilot — where LabSolution
   is neither PIC nor PIP *for the lab's PHI* it is still a **PIC for its own corporate processing**,
   and the product-side NPC corporate filing needs a named DPO contact. **Because the DPO shares a
   surname with the accountable owner, the DPO charter must explicitly document the DPO's
   independence and direct reporting line (RA 10173 IRR Sec. 26)** to preempt an NPC
   independence challenge. *(The appointment letter + charter are the remaining `[NEEDS-HUMAN]`
   artifacts; the appointment itself is decided.)*

5. **Named signatories (DEC-07).** For the VMP / validation dossier:
   - **System owner → Marloe Uy**
   - **Validation lead (executes IQ/OQ/PQ) → Marloe Uy**
   - **QA/regulatory owner (independent approver) → Artis Lindy Pinote**
   - **Pathologist approver → per-customer**, named at each lab's on-site PQ (the lab's RA 4688
     result-release pathologist — not an internal LabSolution appointment).

   Uy executes the validation and Pinote approves it independently, preserving the **executor ≠
   approver** separation auditors look for without inventing headcount the venture does not have.

## Consequences

**Positive**
- **Unblocks the LIS-10 close gate.** Every "DEC-01 owner" cell in the register, NPC checklist,
  and matrix now resolves to a named person; the VMP can carry real signature lines; DEC-02 and
  DEC-07 close with it.
- **Clean accountability line.** One accountable owner (Pinote) spans the topology decision
  (ADR-0006), this allocation, and the dossier/NPC/SaMD — no split-brain ownership.
- **Counsel cost is bounded** to a defined confirmation scope rather than an open-ended outsource.

**Negative / costs / residual `[NEEDS-HUMAN]`**
- **Counsel confirmation is still required** before the allocation is *relied on* — the M1
  "neither PIC nor PIP" premise, the SaMD classification, and the verbatim NPC/ISO clause text are
  reasoned positions, not settled law/text. This ADR records an internal decision; **it is not
  legal advice.**
- **Appointment artifacts remain to be produced** — the DPO appointment letter + independence
  charter, and the signatory sign-offs on the VMP — are named-person paperwork an agent cannot
  generate.
- The **DPO independence** must be visibly documented given the family relationship.

## Alternatives considered

- **DEC-01 option (b) — split ownership** (LabSolution owns dossier + NPC, labs own RA 4688):
  partially adopted — labs *do* own their RA 4688 LTO (it has no vendor provisions), but this is a
  legal fact, not an ownership choice, so it does not change who owns the product side.
- **DEC-01 option (c) — outsource the dossier/NPC to external counsel** under an internal
  accountable exec: rejected. It would hand the product validation dossier and filings to counsel;
  the venture wants internal ownership with counsel only for specialized legal *confirmation*.
- **DEC-02 — outsourced/fractional DPO**, or owner-as-DPO: rejected in favor of a named internal
  designation (Kirsten Pinote) with a documented-independence charter.

## References

- ADR-0006 — deployment topology (M1 pilot / M3 spoke), which sets which model drives the PIC/PIP split.
- `docs/compliance/responsibility-and-deployment.md` — the requirement-by-requirement PIC/PIP
  allocation adopted in Decision 1.
- `docs/compliance/decisions-register.md` — DEC-01/02/07 (now resolved by this ADR).
- `docs/compliance/npc-registration-checklist.md` — DPO designation (§B), registration scope (§A).
- `docs/compliance/validation-master-plan-outline.md` — signatory block (DEC-07).
- ADR-0008 — interface engine / stack / fleet (resolves DEC-04/05/06/08), the sibling leadership
  decisions taken in the same session.
