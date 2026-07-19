# Runbook — X3 QC/calibration guarded go-live (LIS-269 / LIS-173)

**Posture: guarded go-live — TECHNICAL-OWNER AUTHORIZED, PENDING independent QA/regulatory
sign-off before patient go-live.** The system/technical owner + validation lead (Marloe Uy,
DEC-01/DEC-07) has authorized this guarded go-live and accepted the documented residual risk
(recorded 2026-07-19, `docs/compliance/sign-off/LIS-269-x3-guarded-go-live-authorization.md`,
LIS-COMP-SIGNOFF-003). That is **one of two required signatures**. The accountable
QA/regulatory approval is **Artis Lindy Pinote (independent QA approver, DEC-01)** — a distinct
person from the technical owner — and is **not yet recorded**; a technical-owner authorization
does not substitute for it. **Patient go-live is not cleared until Pinote's independent sign-off
lands** (her countersignature on LIS-COMP-SIGNOFF-003 §5, or an attributable comment on LIS-269
in her own name, following the ADR-0019 precedent). Until then this posture is **conditional**,
not effective.

Scope: this runbook governs **only the QC/calibration-misroute residual** on the MAGLUMI X3
native-ASTM path. It does not waive the other verified open go-live gates from the 2026-07-19
X3 production-readiness review (tracked as LIS-267..279 — notably LIS-265 idle-sever silent
loss, LIS-272 missing core X3 seed: the real wire codes FT3 / "FT4 II" / "TSH II" are unmapped,
so real results stage read-only "configuration needed" and QC processing fails on a null testId
until that seed lands, and LIS-38/39 sign-off artifacts). Under this conditional posture — once
Pinote's independent QA sign-off lands (see Posture) — patient results on this path may go live
**for the QC/calibration axis**, conditioned on two things both being true at the same time:

1. **QC-provisioning config is present** — the analyzer profile that seeds `analyzer_qc_rule`
   rows and the calibration rule type it can express both exist (this runbook's companion
   changes: LIS-173 core PR, `deploy/kit/configs/analyzer-profiles/astm/snibe-maglumi-x3.json`).
2. **The operator QC-review SOP below is followed** — the compensating control for the fact that
   the provisioned discriminator is a best-guess, not a proven one.

Do **not** read "QC-provisioning config exists" as "QC routing works." It makes QC routing
*possible* and, via the profile-seed path, *the default* — it does not make it *proven*. That
proof is LIS-266's job, still open.

## Why this is guarded, not green

Chain verified by adversarial review 2026-07-19 (LIS-269):

- The bridge's in-repo `configuration.yml` X3 `qcRule` (`FIELD_EQUALS(O.12, Q)`) is keyed at
  `192.0.2.10` — TEST-NET-1, "never routable" by its own comment — so it has never matched real
  analyzer traffic.
- OpenELIS's registry sync **fully replaces** the bridge's analyzer registry on every sync
  (`attachQcRules`), and until this slice no MAGLUMI/SNIBE analyzer profile existed anywhere, so
  the sync pushed `qcRules: []` — the live entry the bridge actually matches carried **no** QC
  rules at all. That gap is what this slice's profile (§ Provisioning below) closes.
- With empty rules, `ASTMResultParser` falls back to the hardcoded `O.12 == "Q"` check — the same
  guess now encoded (as the active default rule) in the new profile. **No bench capture confirms
  the X3 emits `O.12 = Q`.** Every captured patient O-record to date is
  `O|1|<id>||^^^CODE` — about five fields, shorter than the field this rule targets. If the real
  X3 never populates `O.12`, the rule silently never fires and a QC row falls straight into the
  patient stream, unflagged.
- Calibration is worse: before LIS-173, `AnalyzerQcRule.RuleType` could not even express a
  `CALIBRATION_*` value — `RuleType.valueOf(...)` rejected it at the REST boundary and the
  `chk_qc_rule_type` CHECK constraint rejected it at the DB. LIS-173 makes the type expressible
  and ships one placeholder rule (`CALIBRATION_SPECIMEN_ID_PREFIX`, operand `"CAL-"`) —
  **deliberately inactive** (`isActive: false`). No calibration upload or Sample-ID convention has
  ever been observed from a real X3; `"CAL-"` is an invented placeholder, not a vendor- or
  bench-confirmed value. Shipping it active risked silently reclassifying a real patient specimen
  whose accession happened to start with `CAL-` out of the patient stream — worse than the current
  gap. It stays inactive until an operator confirms the real convention (LIS-266) and flips it on.
- Downstream of classification is sound: a QC-tagged row is staged read-only and never accepted
  into the patient result set (Westgard pipeline wired; see ADR-0019 for the acceptance-gate
  allocation across edge/bridge, edge/sim, and OpenELIS-core). The gap this runbook is about is
  entirely upstream, at classification + provisioning.

## Provisioning (what this slice lands)

- **LIS-173 (core):** `AnalyzerQcRule.RuleType` gains `CALIBRATION_FIELD_EQUALS`,
  `CALIBRATION_FIELD_CONTAINS`, `CALIBRATION_SPECIMEN_ID_PREFIX`,
  `CALIBRATION_SPECIMEN_ID_PATTERN`; liquibase `004-014` widens
  `analyzer_qc_rule.rule_type` and the `chk_qc_rule_type` CHECK constraint;
  `AnalyzerQcRuleServiceImpl.validateRule` accepts the new types.
- **X3 analyzer profile:** `deploy/kit/configs/analyzer-profiles/astm/snibe-maglumi-x3.json`
  (mirrored at `core/openelis/projects/analyzer-profiles/astm/snibe-maglumi-x3.json` per the
  mirror convention in `projects/analyzer-profiles/README.md` — the `deploy/kit` copy, mounted at
  `/data/analyzer-profiles`, is authoritative for deployed environments). Creating the analyzer
  from this profile seeds `configDefaults.qcRules` into `analyzer_qc_rule` via
  `AnalyzerServiceImpl.createQcRulesFromProfile`, so the bridge push-sync
  (`AnalyzerBridgeStartupRegistrar` / `BridgeRegistrationService.attachQcRules`) now has a
  non-empty rule set keyed at the analyzer's real registered IP — the previous "sync wipes it to
  empty" failure mode is closed for whatever rules are provisioned, though the rules' *correctness*
  remains unproven (see above).
- Every value in the profile that claims to discriminate QC/calibration traffic carries the label
  **"PROVISIONAL — pending LIS-266 chassis-attached QC capture to confirm the real X3
  QC/calibration discriminator; do not treat as wire-proven."** verbatim in its `description`.
- **Provisioning order matters:** create the X3 analyzer only on a core that includes the LIS-173
  change (core PR #51). On an older core, `createQcRulesFromProfile` silently skips the
  `CALIBRATION_*` placeholder (per-rule catch, warn-log only) and the skip does **not** self-heal
  on a later core upgrade — profile rules seed at analyzer creation only, so the analyzer must be
  re-provisioned (recreated from the profile) to pick the rule up.

## Required operator QC-review SOP (compensating control)

This SOP is **required**, not optional, for any site running the X3 native-ASTM path before
LIS-266 lands. It exists because the provisioned QC rule is a best-guess default, and the
calibration rule does not fire at all (shipped inactive).

1. **Before go-live at a site:** confirm the `snibe-maglumi-x3` analyzer profile was used to
   create the X3's analyzer record in OpenELIS (Admin → Analyzers), and that
   `GET /rest/analyzer/analyzers/{id}/qc-rules` shows the `FIELD_EQUALS O.12=Q` rule active. This
   is the "QC-provisioning config is present" precondition for go-live.
2. **Daily, for every result batch ingested from the X3:** a lab engineer reviews the *patient*
   result queue (not just the QC queue) for any result that looks like it could be a
   QC/calibrator value that was missed by classification — e.g. a specimen ID matching a QC/lot
   naming convention used at that site, an implausible value for the ordered test, or a result
   landing with no matching patient order. Treat any such finding as a suspected classification
   miss, not a data-entry error.
3. **On any suspected miss:** hold the result (do not release) and capture the raw ASTM bytes.
   Note the production bridge has **no inbound raw-message archive** (ADR-0012 is Proposed and
   edge/sim-only; ADR-0022, Proposed, covers the future H9-style raw archive) — capture at the
   network layer instead (tcpdump/capture rig on the bridge host, per the bench runbook's
   capture tooling), and file it against LIS-266/LIS-269
   with the captured bytes attached. Do not silently correct and move on — a repeatable miss means
   the discriminator is wrong and the profile needs to change.
4. **Calibration:** because the calibration rule ships inactive, no host-side calibration
   classification happens at all yet. Any calibration run must be recognized and handled by the
   operator manually (per existing pre-X3-integration lab procedure) until LIS-266/LIS-38 confirm
   a real convention and the profile's calibration rule is activated with a confirmed operand.
5. **Never auto-accept QC** — unchanged baseline from ADR-0019. Even a correctly-classified QC row
   is staged read-only; acceptance/rejection is an engineer sign-off in OpenELIS-core's QC module,
   never automatic.
6. **When LIS-266 lands:** re-derive the QC discriminator (and, if observed, the calibration
   convention) from the real capture, update `snibe-maglumi-x3.json` accordingly, re-provision, and
   retire step 2's heightened manual review to the normal QC-review cadence. The concrete
   capture-to-proof procedure (replay the captured QC bin through the deployed stack and verify
   read-only QC staging) is `docs/runbooks/snibe-maglumi-x3-bench.md` §9a.

## Residual risk (explicit)

- **QC misclassification into the patient stream is possible and not ruled out.** The active
  default rule (`O.12 == "Q"`) is unconfirmed against real X3 wire traffic; if wrong, QC results
  are not tagged and are not held read-only — they behave exactly like patient results.
- **Calibration classification does not happen at all yet** (rule ships inactive by design, see
  above) — this is a known, accepted gap under the guarded-go-live posture, not a silent one.
- **LOINC/UCUM mappings in the profile (TSH, FT4) are synthetic seeds**, the same ones already
  carried in the bridge's `configuration.yml` ("real dictionary = LIS-38"), not a validated vendor
  dictionary.
- This runbook's SOP is the compensating control for the QC-misclassification, calibration and
  LOINC/UCUM mapping residuals above. The technical owner has accepted
  it as such (LIS-COMP-SIGNOFF-003); it becomes the *QA-accepted* control only when Pinote's
  independent QA/regulatory sign-off is verifiably recorded (see Posture). It does not eliminate
  the risk; it bounds it to "caught by daily human review" instead of "undetected."
- **No patient identity on the X3 wire — the same-day wrong-patient guard cannot fire.** The X3
  sends a bare `P|1` patient record (no id, no name), so every X3 result stages with a blank patient
  hint and the LIS-239 same-day patient-mismatch guard is **structurally inert** on this channel. If
  an operator mis-keys or mis-scans a sample ID so it collides with another **same-day** patient's
  accession, the result attaches to the **wrong patient** and no software check on this wire catches
  it. The compensating control is the staging-UI banner ("No patient identity from analyzer",
  derived server-side per row) **plus the operator procedure in
  [`x3-patient-identity-verification-sop.md`](x3-patient-identity-verification-sop.md)** — a
  **required go-live gate for this channel, not optional reading**. The systematic control
  (order-side cross-check) is LIS-296 and is **not** in place. The residual is pinned in core by
  `useSameDayPatientCollision_blankWireHints_substitutesSilently_LIS270Residual`.
  **Scope note:** this residual is *separate* from the QC residuals above. The daily-review SOP in
  this runbook does **not** bound it — that SOP is QC-classification-focused and does not address
  wrong-patient attachment — and **LIS-COMP-SIGNOFF-003 does not cover it**, having been recorded
  before this residual was identified (LIS-270). Its own acceptance is the LIS-270 go-live gate.

## Traceability

- LIS-269 — X3 QC/calibration provisioning gap (this runbook's parent slice).
- LIS-173 — OE control-plane: `CALIBRATION_*` rule types, liquibase, validation.
- LIS-266 — chassis-attached QC/calibration capture (the still-open proof this runbook stands in
  for).
- LIS-33 — [S3.2] X3 QC results classified host-side, kept out of the patient stream. Its "Done"
  label predates this slice's finding that the discriminator was never wire-verified; the recorded
  disposition (LIS-33 ledger, 2026-07-18) retains it as Done with LIS-269 as the superseding live
  remediation on the native path.
- LIS-270 — X3 wire carries no patient identity; the LIS-239 same-day mismatch guard is inert on
  this channel. Go-live gate = staging banner + operator SOP
  (`docs/runbooks/x3-patient-identity-verification-sop.md`).
- LIS-296 — order-side cross-check: the *systematic* wrong-patient control deferred by LIS-270.
  Open; until it lands, the LIS-270 SOP is the primary defence on hint-less channels.
- LIS-239 / LIS-126 / LIS-128 / LIS-158 — the accept-boundary controls the LIS-270 SOP enumerates
  (and, for LIS-239, the one that cannot fire here).
- LIS-38 — MAGLUMI X3 bench-conformance sign-off (LOINC/UCUM dictionary, framing confirmation).
- LIS-75 — SNIBE MAGLUMI X3 native-ASTM bench capture (`docs/runbooks/snibe-maglumi-x3-bench.md`).
- ADR-0019 — QC-acceptance responsibility allocation (never auto-accept; engineer sign-off owned
  by OpenELIS core) — the downstream acceptance gate this runbook's upstream classification feeds.
