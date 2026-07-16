# Runbook — enabling autoverification (`autoverification.enabled`)

How to turn on the Stage-5 autoverification gate (LIS-55) in a pilot deployment, what it
does when on, what must be true **before** it is turned on, and how to turn it back off.

**Default: OFF.** The flag defaults to `false` in code
(`@Value("${autoverification.enabled:false}")` in
`core/openelis …/autoverification/service/AutoverificationGateServiceImpl.java`); no
deployment ships with it set. Enabling it is a deliberate, owner-approved act governed by
this runbook.

## What the flag does

With `autoverification.enabled=true`, every analyzer-result **accept** is followed by a
gate pass over the accepted analyses. An analysis releases (auto-finalizes) only when
**all** legs pass, fail-closed:

1. **QC-run status** — no active REJECTION-severity Westgard violation and no
   PENDING-evaluation QC result for the (instrument, test).
2. **Reference range** — the persisted result is numeric, finite, and inside the
   configured `result_limits` normal range (absent/equal bounds = "no range configured",
   which passes and is recorded as such).
3. **Delta check** — delegated to the `DeltaCheckService` SPI (LIS-54). FLAGGED holds;
   NOT_EVALUABLE is recorded but does not block.

A releasing analysis gets the **same treatment as human validation** (LIS-226):
Finalized status + released date + audit trail + "Auto-verified by system" note, then the
human path's release side effects — RESULT_VALIDATION notification per result, parent
sample rolled to Finished when it was the last open analysis, registered `IResultUpdate`
updaters, and the FHIR result export (Observation/DiagnosticReport/Task) after commit.
A held analysis stays at TechnicalAcceptance in the human validation queue with a note
recording every failed leg.

## Gating issues — all must be Done before any deployment sets the flag

| Gate | Why | Status check |
|---|---|---|
| **LIS-226** — release side effects | Without them an auto-released result leaves the validation queue but is never exported/notified and its sample never completes (released-but-undelivered). | The gate's release path must call `transformPersistResultValidationFhirObjects`; covered by `AutoverificationGateComponentTest.autoFinalizedLastOpenAnalysis_exportsFhirAndRollsSampleToFinished`. |
| **LIS-54** — delta-check engine | Until the real SPI implementation lands (`@Primary` over `NotInstalledDeltaCheckService`), the delta leg is NOT_EVALUABLE for every result — results release with **no delta protection**. | Confirm the deployed core resolves a real `DeltaCheckService` (startup log / bean listing), not the not-installed stub. |

Also verify the clinical configuration prerequisites in the target lab:

- `result_limits` seeded for every auto-verifiable test (unseeded tests release with
  "no range configured" recorded — confirm that is intended per the LIS-191 ruling).
- Westgard rule configs (`westgard_rule_config`) active for every (instrument, test)
  pair, with REJECTION severity on the rules that must block release. QC without rules
  cannot hold anything.
- QC lots/statistics established so runs actually evaluate (a PENDING evaluation blocks
  release until the async evaluator classifies the run — that is by design).

## Enabling

The core webapp receives deployment properties as JVM system properties via
`CATALINA_OPTS` (same mechanism as `datasource.*`). In the deployment's compose
definition for the `oe.openelis.org` service, append:

```
-Dautoverification.enabled=true
```

to `CATALINA_OPTS`, then recreate the container. There is no seed/migration step; the
flag is read at context startup.

## Post-enablement smoke (per instrument, before leaving the bench)

1. Post an **in-control QC** result; wait for the run to classify ACCEPTED.
2. Send a clean in-range patient result → accept it. Verify: analysis Finalized with an
   "Auto-verified by system" note; parent sample Finished (if last open analysis); FHIR
   Observation + DiagnosticReport present in the FHIR store; notification dispatched if
   the test has a notification config.
3. Send an out-of-range result → accept. Verify it is **held** at TechnicalAcceptance
   with the range reason in the note, and appears in the human validation queue.
4. Post an out-of-control QC value (e.g. > 3 SD) → verify subsequent patient results on
   that (instrument, test) hold with the violated rule named, until the violation is
   resolved by a human.

## Known residuals (accepted, same as the human path)

- The FHIR export runs **after commit** and is asynchronous; an export failure is logged
  loudly (`FHIR export … FAILED — results are released locally but not exported`) but
  not retried by core. Monitor the OE log for that message; re-push is a manual/HIS-side
  concern.
- Notification failures are logged per result and never block a release.
- `IResultUpdate.postTransactionalCommitUpdate` is not invoked — parity with the human
  validation path, where the call is disabled upstream.

## Rollback

Remove `-Dautoverification.enabled=true` (or set `false`) and recreate the container.
Accepted results then stay at TechnicalAcceptance for human validation exactly as before
LIS-55; nothing else changes. Already auto-released results remain released — handle any
that must be recalled through the normal correction workflow.

## Traceability

- LIS-55 — the gate (core PR #33). LIS-226 — release side effects + this runbook.
- LIS-54 — delta SPI. LIS-51 — Stage 5 umbrella.
- ADR-0019 — QC host-classification context for the QC leg.
