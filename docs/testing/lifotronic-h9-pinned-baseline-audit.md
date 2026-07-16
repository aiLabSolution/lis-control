# Lifotronic H9 S1 pinned-baseline audit (LIS-229)

**Audited:** 2026-07-16, read-only.

**Question:** Is analyzer source registration fail-closed, and do the ingress rate and
frame-size controls cover serial at the bridge pin used by the H9 plan?

## Pins checked

- Plan-cited bridge pin: `edge/drivers@55eaf04`.
- Current `origin/main` umbrella pin after `git pull --ff-only`:
  `edge/drivers@de228907332a2befbfa3984f9bd96b12df3e5347`
  (slice synchronized to umbrella `eb1e1a5` before commit).

The relevant blobs and line numbers are identical at both bridge pins.

## Finding

| Question | Evidence at both pins | Verdict |
|---|---|---|
| Unknown source | `MessageNormalizer.java:193–200` logs `Rejecting ... unknown source`, records a failed route, and returns `false` when `AnalyzerIdentifier.identify` produces no registered source. | **Fail-closed.** The older transparent/advisory behavior is not present. |
| Source rate limit on serial | `SerialMessageHandler.java:76` calls `SourceRateLimiter.check(Transport.SERIAL, serialPortPath)` before it builds and routes the envelope. | **Applied to SERIAL.** It is not MLLP-only. |
| Serial frame/message limit | `SerialFrameBuffer.java:53` fixes `MAX_CAPACITY` at 1 MiB; `:406–416` caps growth and discards incomplete buffered data at the cap while preserving completed messages. | **Applied in the serial framer.** |

## Documentation drift

Two umbrella documents still describe the superseded behavior:

- `contexts/edge-drivers/CONTEXT.md:194–196` says rate limiting is MLLP-only and the
  source allow-list is advisory.
- ADR-0015 Decision 4, notably lines 118–123 and its repeated consequence text, says
  serial lacks rate limiting and unknown sources are forwarded.

Those statements are historical residuals and contradict both audited pins. This S1
note records the actual pinned behavior without reopening the accepted ADR. A later
documentation reconciliation should preserve the remaining true residual—shared-JVM,
thread-level channel isolation—while removing the closed LIS-91 claims.

## S1 disposition

The LIS-229 code-only drift acceptance criterion is **MET**. No S4 production change is
needed to establish fail-closed registration, serial per-source limiting, or the serial
1 MiB cap. The real capture, physical DB-9/serial-settings confirmation, and firmware /
host-mode confirmation remain bench-gated.
