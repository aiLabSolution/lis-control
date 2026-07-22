# LIS-269 — MAGLUMI X3 QC/Calibration Guarded Go-Live · Technical-Owner Authorization

| | |
|---|---|
| **Document ID** | LIS-COMP-SIGNOFF-003 |
| **Version** | 1.0 |
| **Date** | 2026-07-19 |
| **Status** | ☑ Technical-owner authorization recorded · ☐ Independent QA/regulatory sign-off PENDING |
| **Programme** | LabSolution LIS — MAGLUMI X3 native-ASTM path |
| **Slice** | **LIS-269** — X3 QC and calibration classification provisioning |
| **Source under authorization** | core PR aiLabSolution/OpenELIS-Global-2#51 (head `dc4ac743a`, LIS-173) · kit PR aiLabSolution/lis-deploy-kit#14 (merged `5c59621`) · umbrella PR aiLabSolution/lis-control#159 (runbook `docs/runbooks/x3-qc-guarded-go-live.md`) |

> **What this is.** A record that the **system/technical owner + validation lead** (Marloe Uy,
> DEC-01/DEC-07) has authorized the **guarded go-live** of patient results on the MAGLUMI X3
> native-ASTM path and **accepts the documented residual risk** from the technical/validation-lead
> standpoint, as of the date above.
>
> **What this is NOT.** It is **not** the independent QA/regulatory sign-off. Under DEC-01/DEC-07,
> the accountable QA/regulatory approver is **Artis Lindy Pinote** (independent QA approver), a
> distinct person from the technical owner. **Patient go-live is not cleared by this record alone**
> — Section 4 remains open. This authorization does not constitute validation, a regulatory filing,
> or legal advice.

---

## 1. Scope of what is authorized

Guarded go-live of **patient results** on the MAGLUMI X3 native-ASTM (E1394-97) path, **scoped to
the QC/calibration-misclassification axis only**. This authorization does **not** waive the other
open X3 go-live gates tracked in the 2026-07-19 production-readiness review (LIS-267..279 — notably
LIS-265 idle-sever, LIS-272 core X3 seed, LIS-38/39 conformance sign-off).

Authorization is **conditioned** on both of the following holding at the same time:

1. **QC-provisioning config present** — the `snibe-maglumi-x3` analyzer profile (core #51 mirror +
   kit #14 authoritative copy) seeds the `analyzer_qc_rule` rows and the `CALIBRATION_*` rule type
   is expressible (LIS-173, core #51).
2. **The operator QC-review SOP is followed** — the required compensating control in
   `docs/runbooks/x3-qc-guarded-go-live.md`.

## 2. Residual risk accepted (technical-owner standpoint)

- **QC misclassification into the patient stream is possible and not ruled out.** The active
  discriminator (`FIELD_EQUALS O.12=Q`) is a documented best guess, **not confirmed on real X3 wire
  traffic** (LIS-266 open). If wrong, QC results are not tagged and not held read-only — they behave
  as patient results (fail-open). Independent adversarial review (2026-07-19) confirmed this is
  **neutral-or-better than the prior zero-rules baseline** and cannot false-positive a real patient
  record out of the stream, but it is not proven safe.
- **Calibration classification does not happen yet** — the profile's `CALIBRATION_SPECIMEN_ID_PREFIX`
  placeholder ships **inactive** (invented `CAL-` operand, not vendor-confirmed); calibration runs are
  handled by existing manual lab procedure until LIS-266/LIS-38 confirm a real convention.
- **LOINC/UCUM mappings are synthetic seeds** (LIS-38), not a validated vendor dictionary.

The operator QC-review SOP (`docs/runbooks/x3-qc-guarded-go-live.md`) is accepted as the
compensating control that bounds this risk to "caught by daily human review" rather than "undetected."

## 3. Basis of authorization

- core #51: CI green on the exact head `dc4ac743a`; round-2 adversarial review **APPROVE** (all
  round-1 findings resolved; inactive-placeholder safety chain proven on real Postgres).
- kit #14: adversarial **APPROVE**, merged `5c59621`.
- umbrella #159: round-1 findings all addressed; Stage-4 site-stack-smoke + X3 e2e pass on the kit
  pin. Verdicts parked in `thoughts/lis-269-adversarial-review-pr51.md`.

## 4. Independent QA/regulatory sign-off — PENDING (blocks patient go-live)

Under DEC-01/DEC-07 the accountable approval is **Artis Lindy Pinote (independent QA approver)**.
That signature is **not** recorded here and **is required before patient go-live**. Until it lands:

- The runbook posture remains **guarded / conditional**, not "effective".
- Pinote records acceptance either by countersigning Section 5 of this document or by an
  attributable comment on LIS-269 in her own name.
- A later session lifts the runbook posture to effective once that signature exists, and re-reviews
  umbrella #159 on its final head before merge.

Also still open (independent of the signature): **LIS-266** — the chassis-attached QC capture + the
§9a replay proof that would move the discriminator from *provisional* to *wire-verified*.

## 5. Signatures

| Role | Name | Basis of signature | Signature | Date |
|---|---|---|---|---|
| **System / technical owner + validation lead** (DEC-07) | Marloe Uy | Technical/validation-lead authorization of the guarded go-live + acceptance of the Section 2 residual risk; recorded at the owner's explicit instruction 2026-07-19 | Marloe Uy (recorded via session, 2026-07-19) | 2026-07-19 |
| **QA / regulatory owner** (accountable; DEC-01) | Artis Lindy Pinote | Independent QA/regulatory acceptance of the guarded go-live + residual risk | ______________ *(PENDING)* | __________ |

## 6. Conditions / notes

> The technical-owner authorization above is recorded exactly as instructed and attributed to Marloe
> Uy — it is deliberately **not** attributed to Pinote, whose independent sign-off (Section 4) remains
> the gate for actual patient go-live. Recording an approval in Pinote's name without her own
> confirmation was declined as a misattribution of an accountable, patient-safety-class sign-off.
