# ADR-0008 — Interface engine (reuse analyzer-bridge), edge stack (Java) & v1 fleet scope

- **Status:** Accepted
- **Date:** 2026-06-25
- **Deciders:** Marloe Uy (System / technical owner), Artis Lindy Pinote (Functional + QA/regulatory owner)
- **Supersedes / Superseded by:** —
- **Resolves:** **DEC-04** (interface engine build-vs-buy), **DEC-05** (stack language),
  **DEC-06** (v1 fleet scope), **DEC-08** (`openelis-analyzer-bridge` license / HOLD-001) in
  `docs/compliance/decisions-register.md`; Open Decisions #6 (interface engine), #2 (stack),
  #4 (fleet) in `LIS_IMPLEMENTATION_PLAN.md` §6 / `LIS_BUILD_AND_INTEGRATION_RESEARCH.md` §13.
- **Relates to:** ADR-0007 (regulatory ownership — names the owner who accepts the validated
  boundary), ADR-0001 (pinned-submodule snapshot = IQ baseline), ADR-0006 (M1 pilot scope).

## Context

The interface engine — the edge layer that ingests analyzer messages (HL7 v2.x / ASTM / serial /
file) and forwards normalized results to the OpenELIS core — was the last open architecture
decision bounding the **validated boundary**. "Build bespoke drivers vs. buy/adopt an integration
engine vs. reuse `openelis-analyzer-bridge`" (DEC-04) drives the L1/L2 test surface, the
per-analyzer conformance scope (REQ-CONF-01/02), the channel-isolation guarantee (REQ-SEC-03), the
threat surface (TB-1/TB-2), and the license inventory (REQ-LIC-01/02). DEC-04 was **blocked on
HOLD-001** — the `openelis-analyzer-bridge` was believed to carry an **undeclared license**
(REQ-LIC-02 = "TBD"), so it could not be safely reused.

**HOLD-001 was resolved by reading the actual license (DEC-08).** The `LICENSE.md` in
`aiLabSolution/openelis-analyzer-bridge` (`develop`) is the **Mozilla Public License 2.0** (full
standard text) **plus OpenELIS's Healthcare Disclaimer** addendum — byte-for-byte the same license
OpenELIS Global 2 itself uses. GitHub's license detector reported `NOASSERTION` / "Other" only
because the appended healthcare disclaimer stops the file matching canonical MPL-2.0; the license
is **not** undeclared. Provenance corroborates it: the repo is a rename of the **"ASTM-HTTP
Bridge"**, the code namespace is `org.itech.ahb.*`, and the legacy Docker image is
`itechuw/astm-http-bridge` — i.e. an **I-TECH UW (DIGI-UW)** project from the same organization
that maintains OpenELIS Global 2 under MPL-2.0. It is a genuine OpenELIS-family, MPL-2.0 component,
not unlicensed code with a license file dropped on top.

The remaining decisions (stack, fleet) follow once the engine is fixed.

## Decision

1. **DEC-08 — license confirmed: MPL-2.0; HOLD-001 lifted.** `openelis-analyzer-bridge` is
   licensed **MPL-2.0 (+ OpenELIS Healthcare Disclaimer)**. MPL-2.0 §2.1 grants a worldwide,
   royalty-free, non-exclusive right to **use, modify, distribute, and exploit commercially**,
   including as part of a Larger Work under our own terms; there is no field-of-use restriction
   and the healthcare disclaimer only removes warranties. **Reuse/fork is permitted.** The
   obligations are the same **file-level (weak) copyleft** already carried for the core, so
   **REQ-LIC-02 is no longer `[NEEDS-HUMAN]`-blocked and folds into the REQ-LIC-01 MPL-2.0
   inventory**:
   - §3.1/§3.2 — when the LIS is distributed to a customer lab, the **source of the MPL-covered
     files** must be offered to that lab under MPL-2.0 (a private repo is fine; the duty runs to
     *recipients*).
   - §3.4 — preserve `LICENSE.md` and do not strip license/copyright notices from covered files.
   - §3.3 — bespoke code in *separate files* may be under our own terms; only bridge-origin
     (covered) files stay MPL-2.0.
   - **Residual hygiene (REQ-LIC-01 inventory, not a blocker):** the sampled source files carry
     **no per-file MPL Exhibit A header** and the repo has **no `NOTICE`** attributing original
     I-TECH UW authorship. MPL allows the directory-`LICENSE`-file fallback, so reuse is valid;
     the clean fix (add `NOTICE` + Exhibit A headers on files we modify) is part of the REQ-LIC-01
     inventory and warrants a final glance by counsel.

2. **DEC-04 — reuse `openelis-analyzer-bridge` as the interface engine** (build-vs-buy option (d),
   now unblocked). It becomes a **validated object** alongside the OpenELIS core. We do **not**
   write bespoke drivers from scratch and do **not** adopt a separate Open Integration Engine
   (Mirth/OIE) for the pilot.

3. **DEC-05 — Polyglot: Java for the validated production runtime, Python for the simulator &
   tooling.** The **production PHI data-path is Java** — the OpenELIS core plus the reused
   **Java / Spring Boot / Maven** analyzer-bridge (`org.itech.ahb`, `pom.xml`, Actuator +
   Micrometer/Prometheus; protocol libs such as `astm-http-lib` already Java). Keeping the live
   data-path single-toolchain gives the smallest **production** L1/L2 validation surface and one
   regression harness for the dossier. **Python is a sanctioned second language** for the
   **analyzer / edge simulator + conformance harness** (LIS-9 / REQ-CONF-02 — currently in
   development) and **supporting tooling / scripts** (e.g. the sign-off PDF builder, seed/data
   tooling), where Python's HL7/ASTM libraries (python-hl7 / hl7apy, MIT/BSD) and fast iteration
   are the best fit.
   - **Boundary (pilot):** Python stays **out of the production PHI data-path**. The simulator is a
     **test instrument** used to validate drivers, so it carries a **test-tool-qualification** duty
     — its own correctness must be evidenced (the conformance-fixture replay self-test, REQ-CONF-02,
     seeds this) — but it is **not** a validated *production* object.
   - **Extension:** introducing a Python **production** component later (e.g. a driver/normalizer for
     an analyzer the Java bridge does not cover) is a **change-control delta (REQ-QMS-03)** that
     explicitly extends the validated runtime, its L1/L2 surface, and the production license
     inventory (adding the Python edge supply chain — typically MIT/BSD).

4. **DEC-06 — v1 fleet PINNED (2026-06-27)** from LabSolution's available test units. v1 is the
   **HL7 v2.x-over-MLLP/TCP** analyzers, **result-ingestion first** (ORU-style → bridge → OpenELIS),
   anchored on the **EDAN H60S** — confirmed **HL7 V2.4 / MLLP** (LIS protocol manual on file; a
   warehouse unit, so an ideal bench reference). The validated path is built against it, then extended.
   Protocols below are confirmed against the manuals repo (✅) or flagged for confirmation (⚠/❌):

   | Unit | Transport / protocol | v1 placement |
   |---|---|---|
   | **EDAN H60S** (warehouse) | ✅ HL7 V2.4 / MLLP (TCP) | **v1 anchor** |
   | **EDAN H99S** | HL7 (EDAN H90 family) | **v1** — H90-series result profile shipped; **order-download gate released for LIS-149** |
   | **RAYTO RT-7600** (hematology) | ✅ TCP (Netport), bidirectional; ⚠ message format unconfirmed | **v1** — confirm HL7 vs vendor format |
   | **SNIBE MAGLUMI X3** | ✅ ASTM E1394-97 / TCP — **native built-in LIS interface** (HL7 v2.5 documented alternative) | **v1.1** — direct-attach to the bridge's ASTM listener; **no SnibeLis middleware, no REQ-PRIV-09 DPA flow-down** *(amended 2026-07-06 — see amendment note below)* |
   | **Seamaty SD1** | ✅ HL7 v2.3.1 / MLLP (TCP); RS-232 also; upload-only (ORU+ACK) — vendor LIS manual on file | **v1** (HL7/MLLP result-ingestion) — added 2026-06-29; bench port/framing capture pending |
   | **ERBA EC90** (warehouse) | ✅ RS-232 serial (ASTM-ish) | **deferred** (serial group) |
   | **HETO AU120** (arriving next) | ⚠ "Konig LIS Protocol V2.1" (manual is Konig AP300; AU120 may differ) | **deferred** — confirm on arrival |

   **v1 = EDAN H60S/H99S + RAYTO RT-7600 + Seamaty SD1** (HL7/MLLP, result-ingestion; SD1 added 2026-06-29). **v1.1 = MAGLUMI X3** (pull
   into v1 only if immunoassay is pilot-critical; since the 2026-07-06 amendment below the pull-in
   no longer carries a SnibeLis middleware or DPA cost — the remaining cost is one TB-1 boundary +
   one REQ-CONF-01 bench report, like any other unit).
   **Deferred post-pilot under change control (REQ-QMS-03):** ERBA EC90 (RS-232 serial) and HETO
   AU120 (incoming), plus general **bidirectional host-query / order-download** expansion. Each
   deferred/added analyzer is one TB-1 trust boundary + one REQ-CONF-01 signed bench report.

   > **`[NEEDS-HUMAN]` — protocol confirmations to firm the pin (3):** RAYTO RT-7600 message format
   > (HL7 vs vendor), EDAN H99S driver = H60S, and HETO AU120 vs Konig AP300 on arrival. *(Seamaty
   > SD1 protocol ✅ confirmed — HL7 v2.3.1 / MLLP, vendor LIS manual on file; bench port/framing
   > capture still pending.)*

   > **⮕ SD-0 reconciliation note (2026-06-29) — does NOT change DEC-06.** The 2026-06-26 **LIS-74
   > availability re-scope** (plan / `docs/testing/stage-1-3-machine-access-checklist.md`) names the
   > **ERBA EC90** the Stage-2 ASTM **bench/build vehicle**, which appears to conflict with DEC-06
   > deferring EC90 "post-pilot." It does not. The conflict was ruled (M. Uy, 2026-06-29; recorded in
   > `docs/compliance/decisions-register.md`, "UPDATE 2026-06-29"): *build-now ≠ pilot-gating* — the
   > **ASTM/serial stack is built and bench-validated now** (Stage-2 slices LIS-23…30 are active dev,
   > validated against the ASTM simulator + the EC90 bench), **but the M1 go-live pilot scope stays
   > exactly as DEC-06 pins it** — EC90, HETO AU120 and the bidirectional path remain
   > bench-validated yet **post-pilot (v1.1)** under change control. So DEC-06's "deferred under
   > change control" means **deferred for go-live, not deferred for development**. The fleet pin and
   > the TB-1 / REQ-CONF-01 pilot surface are unchanged. (The ASTM ADRs 0009/0010 carry the matching
   > vehicle-re-scope note.)

   > **⮕ DEC-06 change-control release (2026-07-04) — H99S order-download implementation gate.**
   > LIS-149 releases the EDAN H99S `QRY^R02 -> ORF^R04` order-download path from the generic
   > deferred-bidirectional bucket into active build and bench scope. The release is deliberately
   > narrow: OpenELIS may resolve a pending order by analyzer barcode, the bridge may answer the H99S
   > worklist query over MLLP, and `edge/sim` carries the matching H99S fixture. This is **not** a
   > fleet-wide bidirectional expansion and does **not** mark the path bench-conformant by itself;
   > H99S order-download still needs real wire evidence and validation-owner sign-off before it can be
   > claimed as supported in the pilot dossier.

   > **⮕ DEC-06 amendment (2026-07-06, LIS-178) — MAGLUMI X3 attaches natively; SnibeLis middleware
   > dropped.** Owner directive (M. Uy, 2026-07-06; Stage-3 epic redesign). The X3 row above
   > originally read *"ASTM E1394 / TCP (via SnibeLis) … +SnibeLis middleware → REQ-PRIV-09 DPA
   > flow-down."* Reading the X3's own IFU (v1.4, App. B "Network interfaces") shows the analyzer
   > has a **native, built-in, bidirectional LIS interface** (`Set → System Setting → Online`)
   > speaking **ASTM E1394-97** — or **HL7 v2.5** as the documented alternative — over TCP to
   > *any* host; SnibeLis was only ever the vendor's default host endpoint, not a required broker.
   > The X3 therefore attaches **directly to the bridge's native ASTM listener** (the analyzer is
   > the TCP client; our bridge is the host, ID `Lis`), consistent with ADR-0015 Decision 1.
   > Consequences: **(a)** the SNIBE-proprietary SnibeLis/SnibeLinker middleware leaves the
   > topology — **one fewer PHI-touching sub-processor**, so the X3's REQ-PRIV-09 DPA flow-down
   > dissolves and SnibeLis drops off the DEC-17 sub-processor candidate register; **(b)** the
   > v1.1 placement, TB-1 surface, and REQ-CONF-01 duty are unchanged (still one trust boundary,
   > one signed bench report); **(c)** the SnibeLis export/DB ingest survives only as a
   > last-resort contingency (LIS-34, demoted) if the X3 firmware refuses a non-SNIBE host
   > (unproven). Work tracked as: LIS-75 (bench capture against our bridge — pins framing incl.
   > the `Enable Checksum` toggle, real Lis-IDs/units), LIS-174 (simplified-envelope framing
   > receive path), LIS-175 (`bridge.analyzers` channel), LIS-176 (SNIBE HL7-dialect fallback),
   > LIS-177 (native host-query). This note amends the row; the 2026-06-27 pin itself is not
   > rewritten.

## Consequences

**Positive**
- **The validated boundary is now fixed:** OpenELIS core (MPL-2.0) + `openelis-analyzer-bridge`
  edge (MPL-2.0), single Java toolchain **on the production data-path** — the VMP's "bespoke vs configured" boundary and the
  L1/L2 surface (VMP §7/§9) can be finalized.
- **License risk closed at zero cost** — no upstream negotiation needed; REQ-LIC-02 collapses into
  the REQ-LIC-01 MPL-2.0 obligation set the venture already plans to honor for the core.
- **Smallest pilot surface** — HL7-v2/MLLP-first, result-ingestion-only, one anchor analyzer keeps
  TB-1 trust boundaries and REQ-CONF-01 conformance reports minimal, consistent with the M1
  "smallest validated base" story (ADR-0006).

**Negative / costs / residual `[NEEDS-HUMAN]`**
- **Reusing the bridge means inheriting its code** as a validated object — its channel-isolation
  model (REQ-SEC-03) and conformance fixtures must be validated as ours, and the **NOTICE / per-file
  MPL header hygiene** must be completed in the REQ-LIC-01 inventory.
- **The v1 analyzer list is not yet pinned** — DEC-06 is settled as a *policy*; the concrete fleet
  is a deployment detail to confirm with the pilot site.
- Adopting the bridge constrains future engine swaps to a **change-control / revalidation delta**
  (REQ-QMS-03) — deliberate, but it is a commitment.

## Alternatives considered

- **Bespoke LabSolution-owned drivers (DEC-04 a):** rejected for the pilot — reinvents a
  field-proven, same-license (MPL-2.0), same-org component and enlarges the L1/L2 validation
  surface for no benefit.
- **Adopt an Open Integration Engine (Mirth/OIE fork) (DEC-04 b):** rejected for the pilot —
  heavier to operate and validate than reusing the OpenELIS-family bridge; revisitable later under
  change control if the fleet outgrows the bridge.
- **Python production drivers on the live data-path (DEC-05 b — full polyglot *edge*):** *deferred,
  not adopted for the pilot* — bespoke per-protocol Python drivers would add a parallel **production**
  validation + supply-chain surface; with the Java bridge reused (DEC-04) it is unnecessary for the
  pilot. (Python **is** adopted for the simulator + tooling per Decision 3; a Python production driver
  remains available later as a change-control delta.)
- **Broad mixed HL7 + ASTM-family + proprietary v1 fleet (DEC-06 b):** rejected — multiplies TB-1
  trust boundaries, the REQ-CONF-01 bench-conformance workload, and the Stage-5 pen-test surface
  for capability the pilot does not need; deferred to post-pilot change-control expansion.

## References

- `aiLabSolution/openelis-analyzer-bridge` — `LICENSE.md` (MPL-2.0 + Healthcare Disclaimer),
  `README.md` (provenance: rename of "ASTM-HTTP Bridge", `org.itech.ahb`, `itechuw` Docker).
- `LIS_BUILD_AND_INTEGRATION_RESEARCH.md` §3 (analyzer fleet inventory by protocol), §4 (HL7 v2 /
  ASTM standards), §5 (reference architecture, channel isolation), §13 (open decisions #2/#4/#6).
- `docs/compliance/decisions-register.md` — DEC-04/05/06/08 (now resolved by this ADR).
- `docs/compliance/traceability-matrix.md` — REQ-LIC-01/02, REQ-SEC-03, REQ-CONF-01/02.
- `docs/compliance/threat-model.md` — TB-1/TB-2 edge boundaries, supply-chain row.
- ADR-0007 — regulatory ownership (the owner who accepts this validated boundary).
