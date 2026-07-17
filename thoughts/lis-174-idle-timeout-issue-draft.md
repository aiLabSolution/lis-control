# Plane issue draft — LIS-174 idle timeout severs the X3's live upload channel

Drafted 2026-07-17 from the LIS-75 bench. **Not filed** — hand to a senior for review, or
file with `scripts/plane_issue.py`. Everything below is bench-evidenced against a physical
MAGLUMI X3 (SN `010101003401230113`); nothing is inferred from the vendor manual.

---

## Suggested metadata

| Field | Value |
|---|---|
| **Title** | `LIS-174 snibe listener: single SO_TIMEOUT severs the X3's long-lived upload channel` |
| **Priority** | **High** — defect in already-merged code, on the critical path for the X3 rollout |
| **State** | triage / ready-for-agent |
| **Blocks** | LIS-32 (E2E), LIS-175 (analyzer channel) |
| **Relates to** | LIS-75 (the bench capture that found it) |
| **Component** | `edge/drivers` (`openelis-analyzer-bridge`), branch `develop`, pin `1023e7a` |

---

## Issue body

### Summary

The SNIBE MAGLUMI X3 listener applies **one** `SO_TIMEOUT` to *every* blocking read —
including the idle wait for the **next** envelope's `ENQ`. The default is **10 seconds**.
Bench capture proves the X3 opens **one long-lived TCP connection and reuses it for every
transaction, indefinitely**, so the bridge tears down a **live, healthy upload channel**
every 10 seconds of quiet.

This does not fail loudly. It fails **intermittently**, and it points the blame at the
network or the analyzer — the worst failure mode for an LIS integration.

### Affected code

`edge/drivers` @ `1023e7a` (branch `develop`):

- `astm-http-lib/.../communication/SnibeAstmCommunicator.java:93`
  `public static final int DEFAULT_SOCKET_TIMEOUT_SECONDS = 10;`
- `SnibeAstmCommunicator.java:163` — `socket.setSoTimeout(soTimeoutMillis)` applied before
  the `ENQ` read, i.e. it also governs the **inter-envelope idle wait**.
- `SnibeAstmCommunicator.java:171-180` — on `SocketTimeoutException` with
  `receivedAtLeastOneEnvelope == true`, returns `null`, and the caller **closes the
  connection**.
- `src/main/java/.../ASTMSnibeListenServerConfigurationProperties.java:46` — default
  inherited from the constant above.
- `configuration.yml:181` — the commented-out site block ships `so-timeout-seconds: 10`
  with the comment *"per-read SO_TIMEOUT, parity with the analyzer's Communicate Timeout(s)"*.

`supportsMultipleEnvelopesPerConnection()` (`:156`) already returns `true`, so the intent
to keep the connection open is present — the timeout defeats it.

### Root cause — two different clocks, one variable

The config comment says the value is *"parity with the analyzer's Communicate Timeout(s)"*.
That conflates two unrelated budgets:

| Wait | What it is | Correct budget |
|---|---|---|
| Next byte **inside** an envelope | the analyzer's `Communicate Timeout` (3s) is how long the **ANALYZER** waits for an **ACK mid-transaction** | ~10s is fine — generous vs the analyzer's own 3s |
| `ENQ` for the **next** envelope (idle) | not a transaction at all — a healthy connection at rest | effectively unbounded (hours) |

The analyzer's `Communicate Timeout` is **not** an idle-connection budget. One constant
currently serves both.

### Bench evidence (LIS-75, 2026-07-17)

**The X3 reuses one connection indefinitely.** Capture session `002` carried **6
transactions across two separate operator upload actions ~90 seconds apart** on a *single*
TCP connection (`raw-20260717-151920-002.bin`, 942B). This supersedes earlier working
models of "one connection per upload" and "one connection per batch" — both were wrong.

**The failure was reproduced twice**, with our bench listener's more forgiving **120s**
timeout (`scripts/x3_astm_capture.py:435`, `conn.settimeout(120)`):

```
15:07:40  upload delivered OK          <- listener up, channel alive
~15:09    listener torn down
15:09-15:17  nothing listening
          operator clicks upload -> "Communication timeout between software and LIS!"
          (LAN healthy, LIS indicator GREEN throughout)
```

Signature in the logs: a **peer-initiated close ~13s after connect with 0 bytes**,
immediately following one of our own `recv timeout — closing session` lines. ~13s ≈ the
analyzer's `Resend Times` (3) × `Communicate Timeout` (3s) — the analyzer writing into a
socket the host already closed, retrying, then giving up.

**At 10s instead of 120s, teardowns are ~12× more frequent**, so the window for an operator
click to land on a dead socket is ~12× wider.

### Impact

- Intermittent, hard-to-reproduce upload failures at any X3 site.
- The analyzer's error text blames the LIS link; the LIS indicator stays **green** (green =
  TCP connect only). Field engineers will chase the network and the analyzer first — we
  did, and it cost a bench cycle.
- Silent-ish: the bridge logs the idle close at `DEBUG` as *"treating as a clean end of
  connection"*, so nothing looks wrong host-side.

### Proposed fix

**Real fix — split the two waits.** Use the configured `so-timeout-seconds` for
intra-envelope reads only; use a separate, effectively-unbounded budget for the idle wait
before `ENQ`. Sketch: read the first `ENQ` with a long (or infinite) `SO_TIMEOUT`, then
tighten to `soTimeoutMillis` for the remainder of the envelope, and restore the long value
after `<EOT>`. Detect genuinely dead peers with TCP keep-alive or an accept-loop bound
rather than by severing idle connections.

**Stopgap** — `so-timeout-seconds: 3600`. Verified on the bench: with it, the X3 delivered
12 transactions across two identities with zero timeouts, and the full
X3 → bridge → OpenELIS chain passed (3 results into `clinlims.analyzer_results`).
Trade-off: a genuinely dead peer is held for an hour — strictly better than cutting a live
channel.

Also update `configuration.yml:181`'s comment: it currently teaches the wrong mental model
and is how the value got to 10 in the first place.

### Acceptance criteria

- [ ] Idle inter-envelope wait no longer closes a healthy connection at `so-timeout-seconds`.
- [ ] Intra-envelope read timeout still bounded (a mid-envelope stall is still detected).
- [ ] Regression test: two envelopes on one connection separated by an idle gap **longer
      than** `so-timeout-seconds` — both must be received.
- [ ] `configuration.yml` shipped default and its comment corrected (no "parity with
      Communicate Timeout(s)" framing).
- [ ] A genuinely dead peer is still reaped (no fd leak).

### Notes for whoever picks this up

- `supportsMultipleEnvelopesPerConnection()` already returns `true` — the design intent is
  right, only the timeout scope is wrong.
- Don't "fix" this by raising the default alone; that just moves the race.
- Bench overlay proving the stopgap: `~/bench-runs/lis75-bridge/` (compose + config, kept
  outside the repo).
- The same class of bug exists in the bench tool (`scripts/x3_astm_capture.py:435`,
  `conn.settimeout(120)`) — flagged, deliberately unfixed, tracked with this issue.
