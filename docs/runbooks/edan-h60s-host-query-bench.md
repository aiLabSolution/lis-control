# Runbook — EDAN H60S bidirectional host-query bench conformance (LIS-181)

Characterize-first bench plan for the **bidirectional / host-query** leg of the EDAN
H60S: the LIS prints an order barcode, the operator scans it on the H60S, the analyzer
issues a host-query (`QRY^R02` / QRD–QRF), the bridge answers with a worklist
(`ORF^R04`), the H60S runs the ordered tests, and the returned `ORU^R01` normalizes and
attaches back to that same order (LOINC-mapped, no orphan sample).

This is the H60S counterpart of the H99S worklist-query gate
(`edan-h99s-bench-conformance.md` §7 / LIS-149). The H60S **northbound** result-upload
leg is already bench-signed (LIS-20, umbrella PR #91); this runbook covers the
**southbound order-download / barcode-query** loop on the physical instrument.

> **Prep artifact, not a completed conformance.** As of writing, LIS-181 is in Backlog,
> gated behind the shared host-query infrastructure (see "Dependency gate" below). The
> **characterization capture** in Step 0 needs no shared infra and can run at the bench
> now; the **worklist-answer** steps (4–5) are gated. Nothing here is signed evidence
> until the exit criteria are met and the validation owner signs.

## Bench update — 2026-07-07 (Step 0 done; responder mechanism demonstrated)

Evidence packet: `~/bench-runs/bridge-h60s/evidence/edan-h60s/20260707-H60-7907/`
(`identity.md` is the authoritative Step-0 record — answers to bench questions 1–6).

**Step 0 (characterization) — DONE.** The physical H60S (`192.168.50.50`) emitted a
`QRY^R02` on barcode scan; the query de-frames cleanly and the six bench questions are
answered from the wire. Confirmed facts (see `identity.md`):

- MSH-3 = `H60^7907`, MSH-4 = `EDANLAB` → EDANLAB / H90-family profile. The synthetic
  fixture's `H60S` / `EDAN` envelope is **refuted**; MSH-12 = `2.4`.
- Barcode subject is in **QRD-8** (`DEV01260000000000012`) — this **matches** the sim
  fixture's QRD-8 and **refutes the manual §3.2.6 example** (which put the subject in
  QRD-9). QRD-9 = `1` (sample sequence), QRD-4 = `1` (the correlation id the answer must
  echo), QRF = `QRF|LIS|<dt>`.
- **MSH-16 = 3 on the host-query** — with 0 = result/sample and 2 = connection-test also
  observed this run, the EDAN MSH-16 map is now `0/2/3` (reconciles the LIS-110 question;
  the manual documents only 0/1). LIS-110 has since shipped the vendor-aware profile:
  EDAN 0/empty→patient, 1→QC (manual-derived, QC-mode capture still pending), any other
  value — including these observed 2/3 frames — held out of the patient stream as a
  fail-closed QC classification (payload-less frames yield no results either way). See
  `edan-h60s-bench-conformance.md` §MSH-16 for the deviation record.

**Responder mechanism (Step 4) — DEMONSTRATED, not yet a physical closed loop.** On the
rebuilt bridge (`edge/drivers` `30b11c8`, LIS-149 + LIS-118 infra), a barcode host-query
in the H60S QRD-8 layout was answered from a **real OpenELIS pending order** with an
`ORF^R04` worklist (`OePendingOrderResolver` → 9 order codes for accession
`DEV01260000000000011`, per the bridge session log — **not** saved to the packet) —
through the **shared** EDAN H90 responder, with **no divergent H60S profile branch
required** (settles that half of Step 6 / AC "field positions"). The returned physical
`ORU^R01` filed all 33 observations under the **barcode** accession, not the OBR-2 counter.

> **Where the attach-fix proof lives:** the packet's `identity.md` / `openelis-attach-evidence.md`
> record the **pre-fix** misfile (results under OBR-2 = `3`) — they predate the fix. The
> post-fix confirmation is *outside* this packet: LIS-182 was already fixed by LIS-149's
> OBR-20 reconcile (`a2152a6`), verified this session by a live OE DB re-query (33 rows under
> the barcode accession, 0 under any counter) and pinned by the real-wire regression test
> `HL7ResultParserLis182Test` (bridge `15feb08`, umbrella PR #102 = this branch's base
> `cc4ad52`). 6/33 analytes mapped; the other 27 are `unmapped_loinc` = the CBC-6
> registration limit (**LIS-112**), not an attach fault.

> **Honesty caveats (why this is not yet Full support):** the demonstrated ORF answer was
> issued to a query from the **NAT'd bench host** (`172.21.0.1`), so it proves the
> *responder mechanism* for the H60S layout — **not** the physical analyzer issuing the
> query, accepting the ORF, and running from it. The ORF worklist wire was **not** saved
> to `orf-hostquery.hl7`, and the QRY→ORF→ORU sequence was not stitched as one physical
> loop (the ORU preceded the QRY this session). Bench question 5 (H60S correlates the ORF
> by QRD-4 echo) is unproven on the physical wire.

**Remaining for Full host-query support (see Exit criteria):**

1. Physical closed loop on the H60S: print barcode → H60S issues QRY → bridge answers ORF
   → H60S runs the worklist → ORU attaches to that order. Capture `orf-hostquery.hl7` +
   the ACK/round-trip.
2. In-place sim fixture graduation (Step 6): swap `edan-h60s-host-query-qry-r02` to
   `synthetic: false` with the real envelope (MSH `H60^7907`/`EDANLAB`, QRD-4 numeric,
   QRD-8 barcode, QRD-9 = `1`, MSH-16 = 3) + capture reference, and align the shared
   host-query test substrate (`test_query.py`, `test_cli.py`, `test_nak.py` — also used by
   the H99S line) off `Q0231-01`/`SPEC-0231`/`RES`. This is host-query *implementation*,
   best landed together with (1) so the built ORF is validated against real wire.
3. Change-control: milestone recorded in ADR-0008 (2026-07-07); go-live validation-owner
   sign-off (Pinote / DEC-01) still owed.

## References

- Vendor spec: `manuals-and-lis-protocol/EDAN/H60S/LIS/LIS-Communication-Protocol-h60.pdf`
  (v1.1, 2022-07-29) — MLLP §1.2.1.2, MSH §3.2.1, PID §3.2.2, OBX §3.2.4, MSA §3.2.5,
  QRD §3.2.6, QRF §3.2.7, message example §6.1, device config Annex 2.
- H99S host-query gate this mirrors: `docs/runbooks/edan-h99s-bench-conformance.md` §7.
- Capture tool: `scripts/h60s_mllp_capture.py` (stdlib MLLP capture-first listener;
  `--replay` for post-bench analysis; tested by `scripts/test_h60s_mllp_capture.py`).
- Shared infra: LIS-149 (QRY handler + ORF builder + barcode↔accession recon),
  LIS-118 (OE-backed `PendingOrderResolver`), LIS-152/153/154 (scope gate, patientId
  fallback, sim bridge-in-loop test).
- Decisions: ADR-0008 / DEC-06 (v1.1 deferral of live bidirectional under change
  control), ADR-0014 (simulator QRD/QRF precedent), ADR-0015 (transport substrate),
  ADR-0013 (H60S milestone / held-back-assertion addendum).
- Sim fixtures: `edge/sim/fixtures/edan-h60s-host-query-qry-r02` (LIS-18, SYNTHETIC),
  `edge/sim/fixtures/edan-h99s-worklist-query-qry-r02` (LIS-149, SYNTHETIC).

## Dependency gate (read before scheduling the full loop)

The analyzer-agnostic host-query machinery is owned by the H99S line and must land (or
run in parallel) before Steps 4–5 can pass. LIS-181's net-new work is **H60S-specific
only**: confirm the H60S query/worklist field positions on the wire, add an H60S branch
to the EDAN H90-series profile if they diverge, graduate the LIS-18 sim fixture to a
real capture, and run the physical signoff.

- **LIS-149** — `QRY^R02` inbound handler, `ORF^R04` worklist builder, barcode↔accession
  reconciliation. *Status caveat:* as of 2026-07-06 the H99S worklist QRY→ORF leg was
  still failing at the analyzer because the bridge ORF used standard HL7 rather than the
  EDAN H90 OBR repurposing. That responder is what Step 4 reuses — track it before
  scheduling the H60S worklist answer.
- **LIS-118** — OE-backed `PendingOrderResolver` (+ per-accession order-menu endpoint).
- **LIS-152 / LIS-153 / LIS-154** — DEC-06 scope gate + identity-fallback guard,
  order-menu patientId fallback, edge/sim bridge-in-the-loop worklist-query test.

**Step 0 (characterization capture) has no such dependency** — it captures the raw QRY
the H60S emits so the profile can be specified, and is the right thing to do at the
bench first.

## Known vs to-confirm wire facts (the characterize-first tension)

LIS-20 proved the **physical** H60S speaks the EDAN **EDANLAB / H90-family** profile,
which the pre-bench synthetic host-query fixture (`edan-h60s-host-query-qry-r02`) does
**not** encode. The vendor manual confirms the profile northbound but is internally
inconsistent about the host-query subject field and ships **no worked QRY/ORF example**.
Treat the field tables *and* the examples as hypotheses; the capture is the arbiter.

| Fact | Manual / LIS-20 says | To confirm on the H60S host-query wire |
|---|---|---|
| MLLP framing | `0x0B <HL7> 0x1C 0x0D`, UTF-8 (§1.2.1.2) | Same for the query direction |
| Roles | Analyzer = TCP client, LIS = server; default port **7999** (ADR-0015 / EDAN training doc; the analyzer's port is set via manual Annex 2, which gives no default) | Confirm port / auto-communication toggle at the bench |
| MSH-3 / MSH-4 | `H60` / fixed `EDANLAB` (§3.2.1; LIS-20) | The synthetic fixture's `H60S` / `EDAN` is **refuted** — record verbatim |
| HL7 version (MSH-12) | Table says `2.4`; §6.1 ORU example shows **`2.3.1`** | Which version the query carries |
| MSH-16 | Documented **0=sample, 1=QC** only (§3.2.1 MSH table); the sim worklist fixture assumes `3` and LIS-20 observed `2`=connection-test | Whether the query sets MSH-16 at all, and to what |
| **QRD subject field** | Table: QRD-8=Who/patient#, QRD-9=What/sample#, QRD-10="used as sample IDs on H60-series"; §3.2.6 example puts `0123456-1` in **QRD-9**; sim fixtures put the subject in **QRD-8** | **Which QRD field carries the scanned barcode** — the central unknown |
| QRD-4 query id | Answer must echo it for correlation | Confirm the H60S correlates by QRD-4 echo (vs subject match) |
| ORF answer shape | H99S: `ORF^R04`, `MSA-1=AA`, `MSA-2`=echo MSH-10, QRD/QRD-8 echo, PID + OBR rows, `MSH-16=3` | Exactly what the H60S accepts as a valid worklist answer |
| OBX (northbound) | Analyte in **OBX-4**, suspect mark OBX-3, value OBX-5, range OBX-7, status OBX-11; histograms `*_PNG_BASE64` in OBX-4 (§3.2.4, §6.1; LIS-20) | Result-to-order attach reuses the shipped H90 parse profile |
| PID | Patient# in **PID-2**, age^unit in PID-3 (§3.2.2; LIS-20) | ORF PID must match what the H60S expects |
| MSA on no-match | `MSA-1=AR`, code `204` unknown key identifier (§3.2.5); "H60 only displays MSA errors as prompts" | The H60S UI behaviour when the barcode has no order |

Bench questions this runbook must answer (record each verbatim in `identity.md`):

1. Does the H60S emit a `QRY^R02` at all when a barcode is scanned? (The H99S did.)
2. Which QRD field carries the barcode — QRD-8, QRD-9, or QRD-10?
3. Is `MSH-16=3` present on the query, or absent / another value?
4. HL7 version on the query — `2.4` or `2.3.1`?
5. Does the H60S correlate the `ORF^R04` by the QRD-4 query-id echo, by subject, or both?
6. Does the barcode the LIS prints match, byte-for-byte, what the H60S puts on the wire?

## Evidence packet

Create one run directory before starting:

```text
evidence/bench/edan-h60s-host-query/<YYYYMMDD>-<serial>/
```

Collect at minimum:

| Artifact | Required content |
|---|---|
| `identity.md` | Model, serial, firmware/software build, protocol version, operator, date/time, and the answers to bench questions 1–6 above. |
| `nameplate.jpg` | Physical nameplate / device identity screen. |
| `network-settings.png` | Analyzer IP/gateway/mask and LIS IP/port (default 7999). |
| `h60s-hostquery.pcap` | Full packet capture across connection test, barcode scan, `QRY`, `ORF`, `ORU`, and ACKs. |
| `raw-*.bin` + `annotated-*.log` | Output of `scripts/h60s_mllp_capture.py` (Step 0): raw bytes + de-framed summary. |
| `qry-hostquery.hl7` | De-framed `QRY^R02` (MSH-3/4/9/16, QRD-4, and the QRD subject field(s) recorded verbatim). |
| `orf-hostquery.hl7` | De-framed `ORF^R04` worklist answer (`MSA-1=AA`, MSA-2 echo, QRD echo, PID + OBR rows). Required only for the full-support exit (Steps 4–5). |
| `openelis-pending-order.json` | OE pending-order lookup for the scanned barcode, showing the reconciled accession + mapped LOINC/test rows. |
| `oru-message.hl7` + `ack.hl7` | The returned `ORU^R01` and the LIS ACK (`MSA-2` = echo of inbound MSH-10). |
| `openelis-result.png` | OE proof the result ingested under **Results → Analyzer → EDAN H60S**, mapped to LOINC, `read_only=false`, attached to the queried order. |
| `edge-sim-roundtrip.txt` | `edge-sim` validate/normalize/roundtrip/worklist-query output after fixture graduation. |
| `signed-conformance-report.pdf` | Final validation sign-off. |

If any artifact contains PHI, do not commit it; redact before sharing outside the
validation evidence store. Use bench-only identifiers throughout.

## Test plan

### Step 0 — Characterize-first capture (NO shared infra required)

Run this first, on its own, to learn the H60S host-query wire before trusting any
assumption. This is the same discipline LIS-20 used northbound.

1. On the bench host, start the capture-only listener on the LIS port:

   ```bash
   python3 scripts/h60s_mllp_capture.py --port 7999 --outdir ./h60s-capture
   ```

   (Add `--ack` only if the H60S needs an acknowledgement to proceed past a
   connection test — it returns a minimal `MSA|AA`, **not** an `ORF` worklist, and the
   analyzer is expected to report "no orders" / wait for an answer that never comes.
   The QRY capture is the deliverable either way.)

2. Configure the H60S LIS settings (Annex 2): MLLP, LIS IP = bench host, port 7999,
   auto-communication as needed. Run the analyzer connection test.
3. Create a bench-only order with a known barcode; scan (or key) that barcode on the
   H60S so it issues a host-query.
4. Read the tool's `CAPTURE SUMMARY`. Record verbatim: MSH-3/4/9/10/12/16, the
   `LAYOUT verdict` (expect `EDANLAB`), the QRD-4 query id, and the QRD-8 / QRD-9 /
   QRD-10 candidate subject values — the tool prints all three because which one holds
   the barcode is unconfirmed. Post-bench, re-analyze the archive with
   `python3 scripts/h60s_mllp_capture.py --replay ./h60s-capture/raw-*.bin`.

Pass criteria (characterization exit — see Exit Criteria):

- A raw `QRY^R02` is on disk, de-frames cleanly, and MSH-3/MSH-4 match the EDANLAB
  profile (or the deviation is recorded).
- The QRD field carrying the barcode is identified from the wire and reconciled against
  the barcode the LIS printed.
- Bench questions 1–6 are answered in `identity.md`.

### Step 1 — Physical identity and protocol confirmation

As `edan-h99s-bench-conformance.md` §1, for the H60S: photograph the nameplate, record
serial/build, confirm the unit is an H60S and covered by the H90-series protocol, and
that captured HL7 shows `MSH-3` = `H60` with `MSH-4` = `EDANLAB`.

### Step 2 — Network and MLLP setup

As the H99S runbook §2: static IP/gateway/mask, LIS IP + port 7999, start packet
capture, verify the listener, run the connection test. Confirm the analyzer is the TCP
client and framing is `0x0B … 0x1C 0x0D`.

### Step 3 — Barcode ↔ accession reconciliation

1. Print an order barcode from the LIS for a bench-only OpenELIS order with a known
   accession.
2. Scan it on the H60S and confirm (from the Step 0 capture) that the barcode the LIS
   printed is exactly what the H60S puts in the QRD subject field.
3. Document the reconciliation rule: barcode-shaped identifiers (short alpha prefix +
   long digit run, e.g. `DEV…`) canonicalize to the OE accession; anything else is
   exact-match only; a barcode whose digit candidates match more than one sample is
   **refused** (no worklist), not guessed — same narrow contract as LIS-149.

### Step 4 — Worklist answer via the shared responder (GATED on LIS-149/118)

1. Route the captured `QRY^R02` through the shared bridge query responder (LIS-149). If
   the H60S field positions diverge from the H99S, add an **H60S branch** to the EDAN
   H90-series profile, gated on `MSH-3.1` / `MSH-4=EDANLAB` (consistent with the LIS-99
   profile gate) — do not fork the responder.
2. Resolve the scanned barcode to the OE order via the OE-backed `PendingOrderResolver`
   (LIS-118) and answer with an `ORF^R04` in the H60S's expected format.
3. Capture `qry-hostquery.hl7`, `orf-hostquery.hl7`, and `openelis-pending-order.json`.

Pass criteria:

- Response is `ORF^R04`; `MSA-1=AA`; `MSA-2` echoes the inbound `QRY` `MSH-10`.
- The QRD-4 query id (and whichever QRD subject field the H60S used) is echoed so the
  analyzer correlates the answer.
- `PID` identifies the bench-only patient; every `OBR` order row maps to an OpenELIS
  pending test configured for the analyzer.
- If the query returns no order rows, check the OpenELIS log for an "ambiguous
  host-query lookup" warning before assuming a mapping gap.

### Step 5 — Result-to-order attach (GATED)

The H60S runs the ordered tests and sends `ORU^R01`. Confirm it normalizes (analyte in
OBX-4, LOINC-mapped via the shipped H90 profile) and attaches to the **same** order —
no orphan sample. The LIS ACK's `MSA-2` echoes the inbound `MSH-10`.

### Step 6 — Fixture graduation + profile branch (two-level)

Per the edge-slice rule, land in **both** the production bridge (`edge/drivers`) and the
`edge/sim` mirror:

- Graduate `edge/sim/fixtures/edan-h60s-host-query-qry-r02` from the synthetic clean-HL7
  layout to the real H60S QRD/QRF capture (`synthetic: false`, EDANLAB layout, capture
  reference), and mirror any bridge fixture.
- If Step 0 showed the H60S query positions diverge from the H99S, land the H60S profile
  branch in the bridge first, then bump the umbrella pin (`/pin-bump`).

### Step 7 — Failure / retry observation

As the H99S runbook §8: one controlled negative observation — e.g. scan a barcode with
no matching order and confirm the H60S surfaces the `MSA-1=AR` / code-`204` refusal as an
operator-visible prompt without altering patient-result state; or drop the listener and
confirm reconnect-on-next-send.

## Exit criteria

**Characterization exit** (Step 0, no shared infra — the deliverable available now) —
✅ **MET 2026-07-07** (packet `20260707-H60-7907`, see Bench update above):

- ✅ A raw H60S `QRY^R02` is captured, de-frames cleanly, and the EDANLAB profile is
  confirmed (`H60^7907` / `EDANLAB`; synthetic `H60S`/`EDAN` envelope refuted).
- ✅ The QRD barcode-subject field is identified from the wire (**QRD-8**) and reconciled
  to the LIS barcode byte-for-byte; bench questions 1–6 answered in `identity.md`.
- ✅ No divergent H99S H90 layout branch is required — the shared responder answered the
  H60S QRD-8 query (envelope/value differences only: QRD-4 numeric, QRD-9 = `1`, MSH-16 = 3).

**Full host-query support** (Steps 4–5, gated on the shared infra):

- `qry-hostquery.hl7`, `orf-hostquery.hl7`, and `openelis-pending-order.json` are in the
  evidence packet, satisfying Step 4 pass criteria (MSA-2 echo, QRD echo, barcode↔
  accession reconciliation).
- The returned `ORU^R01` attaches to the queried order, LOINC-mapped, no orphan sample,
  with OE result proof.
- The bridge/OpenELIS implementation used is recorded by git SHA.
- A change-control note is recorded against DEC-06 / ADR-0008 for pulling live H60S
  bidirectional into scope (REQ-QMS-03), and the H60S supported-matrix row is updated.
- The validation owner signs the LIS-181 conformance report.

## Follow-up slices to file if needed

- H60S EDAN H90-series **query/worklist profile branch** in `edge/drivers` if Step 0
  shows the H60S QRD/QRF/ORF positions diverge from the H99S.
- MSH-16 semantics reconciliation for the H60S (0/1/2/3) if the query's MSH-16 differs
  from the manual's documented 0/1 (relates to LIS-110).
- EDAN OBX-11 finality handling in `edge/sim` if H60S milestone ingest must be a green
  exit criterion (relates to the H99S OBX-11 follow-up).
