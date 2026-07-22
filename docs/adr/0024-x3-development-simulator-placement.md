# ADR-0024 — MAGLUMI X3 development simulator: placement, dependency policy, headless-first

- **Status:** Accepted
- **Date:** 2026-07-22
- **Deciders:** Marloe Uy (system/technical owner); Artis Lindy Pinote (validation owner) — ratified jointly 2026-07-22
- **Slice:** LIS-317 (Phase 0.1 of the X3 development-simulator programme, epic LIS-316)
- **Supersedes:** ADR-0004 §1 (the placement clause only — see "Relationship to ADR-0004")
- **Relates to:** ADR-0001 (submodule-umbrella topology); ADR-0012 (raw message archive);
  ADR-0015 (edge substrate); `thoughts/plans/2026-07-20-maglumi-x3-dev-simulator.md` rev-3
  (the approved plan this ADR opens)

## Context

ADR-0004 placed the analyzer simulator harness umbrella-side under `edge/sim/` and said so
**conditionally**: *"until the `edge/drivers` submodule exists. When it does, `edge/sim` can move
into it or alongside it; nothing here assumes a fixed home."*

That condition has expired. `edge/drivers` exists and is pinned in the umbrella. The placement is
therefore **inherited rather than decided** — it rests on a premise that is no longer true, and
nothing records why `edge/sim` should stay where it is now that the stated trigger for moving it
has occurred.

The X3 development simulator (epic LIS-316) is a substantially larger build than the ADR-0004
harness: a device model, a session driver, a scenario engine, fault injection, capture tooling and
an operator interface. Committing that investment to a location on an expired premise is precisely
the kind of silent inheritance the ADR process exists to prevent. The approved plan makes recording
this decision its first deliverable.

## Decision

### 1. The simulator engine stays in `edge/sim/`, on its own merits

Not because ADR-0004 put it there, but because:

- **The substrate is already there and is load-bearing.** The codec layer, the fixture corpus and
  its JSON schema, the raw-message archive (ADR-0012), the CI job, and the cross-repo payload digest
  anchor that ties the Python fixtures to the Java bridge tests all live in `edge/sim`. Moving the
  engine would either split it from that substrate or drag the substrate with it, and the digest
  anchor is asserted on both sides of the language boundary — relocating it is a coordinated
  two-repo change with no benefit.
- **`edge/drivers` is production code; the simulator is not.** The bridge is clinical-path software
  that runs in front of a live analyzer. The simulator is a non-clinical development tool that must
  never run in production, and the approved plan gives it fail-closed target allowlisting, an
  environment gate with no production value, and a kill switch precisely to keep it out. Housing a
  tool whose entire safety posture is "must not reach production" inside the production component
  would put those guarantees on the wrong side of the boundary and invite accidental packaging.
- **Different release cadence and different reviewers.** A simulator change does not warrant a
  bridge pin bump, and bridge CI has no reason to gate simulator-only work.

The umbrella-side exception to ADR-0001 that ADR-0004 accepted as *temporary* is hereby made
**permanent for the simulator**, with the reasoning above as its standing justification. This does
not reopen the placement of any production component.

### 2. The engine is stdlib-only; the interface is an optional extra

The engine keeps an empty runtime dependency set, so the bench box can run it as plain
`PYTHONPATH=edge/sim/src python3 -m edge_sim …` with no package manager present. This preserves
ADR-0004's stdlib-only posture, which has proven its worth on a bench where tooling availability is
not guaranteed.

The terminal interface goes in an optional dependency group. **CI installs the base group only**, so
the interface can never become load-bearing for the test suite.

### 3. Headless-first: every interface is a downstream consumer

The engine is headless and exposes a typed event stream. The terminal interface and the static
HTML/Markdown export both consume that stream; neither owns protocol logic, and neither is required
to run a scenario.

This is what makes the terminal-versus-web decision reversible. The plan chooses a terminal
interface — the debugging artifact is a control-character byte stream that terminals render
natively and browsers do not, and a web UI is three surfaces to maintain instead of one — while
recording that reviewer accessibility is a genuine cost of that choice, paid down by the exported
artifact. If exported artifacts prove insufficient for the validation owner's review, a web UI can
be added as a further consumer of the same event stream without touching the engine.

### 4. Fixtures remain the contract

ADR-0004's second decision stands unchanged and is reaffirmed: the durable artifact is the fixture —
payload bytes plus a schema-validated manifest — not the harness that consumes it. The simulator is
one consumer among several, alongside the capture tooling and the Java bridge tests.

## Relationship to ADR-0004

ADR-0004 remains **Accepted**. Its fixture contract, its Python choice, its transport abstraction
and its provenance requirements are all still in force and are not reopened here.

Only its **§1 placement clause** is superseded, because that clause was explicitly conditional and
its condition has since been met. This ADR replaces a conditional, expiring placement with an
unconditional one and states the reasoning that ADR-0004 could not, since `edge/drivers` did not
exist when it was written.

## Consequences

**Positive**

- The placement of a substantial programme rests on a recorded decision rather than an expired
  premise.
- The safety boundary is structural: non-clinical tooling sits outside the production component.
- Simulator work stays a single-repo change for most phases, avoiding pin-bump overhead. (Phases
  that touch the deploy kit or core are called out in the plan and remain two-level.)
- The interface decision is reversible without re-architecting.

**Negative / costs**

- The umbrella keeps a permanent Python component, a standing exception to ADR-0001's
  "components live in submodules". Accepted deliberately: it is test tooling, not a deployable.
- Contributors must remember that `edge/sim` mirrors bridge behaviour and that the shared payload
  digest is asserted in both repositories — a codec change is a coordinated two-repo change even
  though the simulator itself is umbrella-only.
- Keeping the engine stdlib-only constrains implementation choices; the optional-extra split adds a
  small amount of packaging discipline.

## Notes

- This ADR records placement only. The programme's other ratified decisions — report watermarking,
  measurement-content re-synthesis and its forward-only grandfathering, unverifiable-target
  semantics, retention, and scope — live in §17.3 of the approved plan, with the prerequisites that
  survived approval in §17.3.1.
- The simulator cannot prove instrument-originated behaviour. That ceiling is stated in the plan and
  in the tool's own documentation, and no placement decision changes it.
