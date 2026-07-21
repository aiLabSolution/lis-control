# Shape-preserving derivation specification

**Version:** 1.0 — 2026-07-22
**Status:** Filed under LIS-319 (Phase 0.5). First *use* of this spec — any actual
re-synthesis — additionally requires the validation owner's review of this document, because
the decision it implements (§17.3 decision 8 of
`thoughts/plans/2026-07-20-maglumi-x3-dev-simulator.md`, rev-3) was a joint owner call.
**Authority:** ratified decision 8 / 8b (2026-07-22, both owners) and its execution
conditions in plan §17.3.1 and §17.3.8.

## 1. Purpose and scope

Ratified decision 8 replaces the measurement content of committed analyzer captures and
fixtures with synthetic content: committed artifacts become **structurally derived**, and the
pristine bytes live only in the offline validation evidence store. This spec defines the
*only* permitted transformation from a pristine capture to a committable derived artifact.

Plan §17.3.1 makes this document a hard prerequisite: **no fixture may be re-synthesized
before this spec exists**, because unconstrained fresh values change field widths, field
widths change byte offsets, and byte offsets are the framing/segmentation evidence
(pipelined `<ETX><EOT>` writes, record chunking, R-record timestamp position) that the
captures exist to protect.

**Forward-only (decision 8b).** The already-committed 2026-07-17 evidence and the graduated
`snibelis-maglumi-x3-result-upload` fixture are formally grandfathered and are **not**
rewritten under this spec. The separate PHI purge tracked against capture `fcf4a5d8` is
**not** covered by that grandfathering and is disposed of independently.

This spec authorizes a transformation, not a graduation: fixture graduation stays with
LIS-276 (quarantine-first intake, ledger review — see `README.md` in this directory), and
nothing here upgrades what simulator-derived artifacts can prove (plan §17.3.2).

## 2. Definitions

- **Pristine artifact** — the raw capture exactly as received from the instrument, held
  only in the offline validation evidence store, never committed.
- **Derived artifact** — the committable re-synthesis of a pristine artifact produced under
  this spec. Its manifest `capture` block declares `source_kind: "bench-derived"` and cites
  the pristine artifact's digest (`raw_digest`), which only the offline store can verify.
- **Derivation** — the deterministic transformation pristine → derived: identity fields,
  measurement values, ranges, and result timestamps are substituted; everything else is
  preserved under the invariants below.
- **Write / segmentation record** — the per-write chunking observed on the wire, i.e. the
  `RECV <n>B` boundaries in the annotated log. Which control tokens and records shared a
  write is bench evidence (e.g. `<ETX><EOT>` pipelined in one write), not an artifact of
  capture tooling.

## 3. Invariants — what derivation MUST preserve

- **I1 Session grammar.** Envelope count and order, and the exact sequence of control
  tokens (`ENQ`/`ACK`/`STX`/`ETX`/`EOT`, and `NAK` if present) across the session.
- **I2 Segmentation.** The derived artifact has the same number of writes, and each write
  covers the same span of records and control tokens as the corresponding pristine write.
  Byte counts per write are **re-derived from the derived bytes** — they are not copied
  from the pristine artifact and not required to equal it (identity-token substitution may
  change widths, §4 S1). A write that gains or loses a record or control token is a
  derivation error.
- **I3 Record grammar.** Record-type sequence per envelope, per-record field count,
  delimiter bytes (`|` `\` `^` `&`), `CR` positions relative to record boundaries, and the
  terminator-record shape are unchanged. Field *ordinality* is evidence (the R-record
  completion timestamp sits at field 13 on this wire, not the KB-documented 12) and must
  survive byte-identically at the grammar level.
- **I4 Field shape for measurement content.** Every substituted measurement value, range,
  and timestamp keeps its exact byte width and per-byte character class: digit → digit,
  decimal point and spaces fixed in place, alpha case preserved, punctuation and separator
  forms (e.g. the `<sp>-<sp>` range separator) byte-identical. Measurement substitution
  therefore never moves a byte offset.
- **I5 Encoding.** 7-bit ASCII stays 7-bit ASCII; the manifest's declared encoding is
  unchanged. Derivation never introduces bytes outside the pristine artifact's character
  repertoire.
- **I6 Framing features.** Checksums, frame numbers, and line terminators are neither
  introduced nor removed. On a wire profile that carries checksums, the checksum is
  **recomputed** after substitution — the only permitted byte difference beyond substituted
  fields — and the recomputation is recorded in the ledger.
- **I7 Semantic consistency.** Abnormal-flag/range relationships are preserved: if the
  pristine result was in-range (`N`), the derived value lies inside the derived range;
  out-of-range and qualified results keep their relationship and their flag bytes.
  Timestamp ordering and inter-timestamp intervals are preserved exactly (§4 S3).

## 4. Substitution rules — what changes, and how

- **S1 Identity fields.** Patient/operator/specimen identity fields take canonical
  redaction tokens (see `README.md`, canonical token vocabulary). For derived artifacts,
  tokens are **not** required to be length-preserving — the fixed-width canonical token
  eliminates the residual by which a length-preserving redaction discloses the original
  name's length (plan §11.3, risk R4). This is the one substitution class allowed to change
  field width; I2 absorbs the offset shift by re-deriving segmentation.
- **S2 Result timestamps.** All timestamps re-base to the fixed synthetic epoch
  **T0 = 2030-01-01T00:00:00**: one constant delta per pristine artifact maps its earliest
  timestamp to T0, and every other timestamp shifts by that same delta, preserving order
  and intervals (I7). Formats and widths are unchanged (14-char `YYYYMMDDHHMMSS`;
  date-only fields shift by the same delta's date part). The delta and the original
  timestamps appear **only** in the offline store — never in the committed artifact or its
  ledger, because result timestamps are part of the value+timestamp+identity linkage the
  re-synthesis exists to break.
- **S3 Measurement values and ranges.** Fresh values are generated deterministically from a
  recorded seed, shape-preserving under I4, and are asserted **unequal** to the pristine
  values field-by-field (a derivation that reproduces a real value has failed). Ranges are
  substituted under the same rules, then I7 is re-checked.
- **S4 Everything else is preserved verbatim.** Protocol identity (sender/receiver IDs,
  protocol version, delimiter declaration), assay codes, units, flags, sequence numbers,
  and all structural bytes. These are conformance evidence, not personal or measurement
  content, and substituting them would destroy the artifact's purpose.

## 5. Determinism and provenance

- Same pristine artifact + same spec version + same seed ⇒ byte-identical derived artifact.
- The transformation ledger (`sanitization.json`, shape defined by the sanitize tooling)
  records: this spec's version, the seed, the epoch T0, and per-field substitution entries
  (record, field, class, occurrences). It records **no original values, no original
  lengths, no per-field deltas, and no absolute paths.**
- The manifest `capture` block for a derived artifact carries
  `source_kind: "bench-derived"`, `raw_digest` = the sha256 of the **pristine** artifact
  (offline-verifiable only — CI cannot check it, by design), and a `derivation` block
  citing this spec and the ledger.
- Citation discipline (plan Appendix D.3): documentation, manifests, tests, and commit
  messages cite the capture session id and digest — they never inline pristine measurement
  values.

## 6. Verification checklist

Before a derived artifact may leave quarantine, verify mechanically (tooling lands with the
graduation slice; until then the checklist is executed and recorded in the ledger review):

1. Parse pristine and derived streams; assert I1, I2, I3 (grammar-level equality; per-write
   record/token spans equal).
2. Assert I4 masks: every substituted measurement field byte-classes identically; every
   non-substituted byte outside checksums is identical.
3. Assert I5 (ASCII) and I6 (framing features; checksums recomputed correctly if present).
4. Assert I7: flag/range consistency; timestamp order and intervals preserved.
5. Assert no pristine identity or measurement byte sequence survives anywhere in the
   derived bin, derived log, or ledger (search both text and hex renderings).
6. Assert determinism: re-run with the recorded seed reproduces the artifact
   byte-for-byte.
7. Anti-vacuity (LIS-149 rule): any test consuming a derived artifact must anchor to the
   pristine digest recorded in the manifest — structural masks plus the offline anchor,
   never self-consistency alone.

## 7. Consequential rewrites this spec triggers when first used

Recorded here from plan §17.3.8 so the first re-synthesis slice inherits them: the L3
conformance layer drops byte-for-byte assertions for committed artifacts in favor of
structural + segmentation conformance with declared value-field masks; the golden digest
anchor asserted in both `edge/sim/tests/test_snibelis.py` and the bridge's
`SnibeSimplifiedEnvelopeSessionTest` migrates **together** (two-level edge slice); ACs
0.3/0.6/1.1/1.2 reword accordingly; U1's byte-compare runs against the offline store.

## 8. Change control

This spec versions monotonically; the ledger cites the version used. Any change to the
invariants or substitution rules re-opens the decision-8 execution conditions and requires
both owners' review, same as the decision itself.
