# AC6 host-id mismatch run — 2026-07-17 15:17–15:48

Sixteen capture sessions against `scripts/x3_astm_capture.py` (concurrent,
simplified-ACK mode), MAGLUMI X3 SN `0101010034012301113`, run to settle
LIS-75 AC6: *does the X3 require the configured `Host ID` to match the
receiving host (as SnibeLis did)?*

**Conclusion: NO — no host-name match is enforced.** AC6 → MET.

| Session | Bytes | What it shows |
|---|---|---|
| `…-151920-002` | 942 B | Baseline, `Host ID = Lis`: six envelopes (FT3 / FT4 II / TSH II ×2) from two operator upload actions ~90 s apart, **all on one reused connection** — the long-lived-reuse wire-fact cited by the bring-up runbook and the LIS-174 idle-timeout issue. |
| `…-152842-006` | 480 B | `Host ID` deliberately set to **`NOTLIS`**: the software stamps `NOTLIS` into the H-record receiver-ID field (**H-10**; sender H-5 stays `Maglumi X3`) and **delivers the full 3-envelope batch anyway**, every token ACKed, LIS indicator green throughout. |
| all others | 0 B | Bare status connects (LIS-green keepalive-style connections); archived for completeness. |

PHI note: the O-record patient-name field in sessions 002 and 006 is redacted
to the same-length token `PATIENT-REDACTED-1` in both the raw `.bin`s and the
annotated logs (`decode=` and `hex=` lines). Pristine captures live only in
the offline validation evidence store. All other bytes are verbatim.

Consequences for the bridge: H-record identity fields are operator-editable
free text — informational only, never route or validate on them
(`docs/runbooks/snibe-maglumi-x3-bridge-openelis-bringup.md`, Step 3).

These captures are live test vectors, not just archives — wire-replay one
against any host with `scripts/x3_astm_capture.py --replay <raw.bin>
--to HOST:PORT` (per-token ACK pacing; `--gap N` idles between envelopes on
the same connection, reproducing the LIS-265 teardown when N exceeds the
host's idle timeout). `scripts/test_x3_astm_capture.py` round-trips sessions
002 and the 13:35 first capture byte-for-byte in CI.
