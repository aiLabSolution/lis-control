# Framing classification — MAGLUMI X3, 2026-07-23 client-lab bench (AC3)

**Verdict: SIMPLIFIED** (`ENQ STX <records> ETX EOT`, ACK per control token; no frame
numbers, no checksum, no LF).

## Evidence

- Wire capture: `raw-20260723-203124-023.bin` (139 B) / `annotated-20260723-203124-023.log`.
  Tool summary: `Framing: SIMPLIFIED (bare STX (no frame number), no checksum, no LF)`,
  signals `ENQ=True STX=True ETX/ETB=True LF=False frame#=False checksum=False`.
- Analyzer-side log: `analyzer-pc-online-logs/20260723/online_ASTM.log` records the same
  session from the analyzer's perspective (`--> <ENQ>` … `<-- <ACK>` … `--> <EOT>`),
  independently confirming the 4-point ACK cadence.
- Analyzer config cross-check: `Enable Checksum` is **UNCHECKED** on the Online screen
  (`online-screen-before.jpg`). Tool classification and toggle state **agree**.

Host ACK cadence used: `simplified` (ACK on ENQ, STX, ETX, EOT). Analyzer accepted it —
LIS indicator green, no NAK, no retransmit, session closed cleanly with EOT.

## Observed byte-level detail

```
--> <ENQ>                    <-- <ACK>
--> <STX>                    <-- <ACK>
--> H|\^&||PSWD|Maglumi X3|||||Lis||P|E1394-97|20260723<CR>
    P|1<CR>
    O|1|PATIENT-REDACTED-1||^^^T4<CR>
--> R|1|^^^T4|119|nmol/L|52 - 127|N||||||20260422111529<CR>
--> L|1|N<CR><ETX><EOT>      <-- <ACK> (ETX)  <-- <ACK> (EOT)
```

Note the record stream arrives in **multiple TCP segments** (77 B: H/P/O, then 52 B: R,
then 8 B: L+ETX+EOT) with a single STX at the start and no per-segment framing — a receive
path must accumulate until ETX, not treat one `recv()` as one message.

## Delimiters (from H-2, matches the Online screen)

Field `|` · Repeat `\` · Component `^` · Escape/"Bounce" `&`

## Idle-timeout behaviour (operational finding, not framing)

The capture tool closes an idle session after 120 s. The analyzer logs each such close as
`--- Lis Is Blocked.` and reconnects ~2 s later (`--- Lis Is Ready.`), repeatedly, all
evening. The analyzer recovers silently, but this is what a host-side idle timeout looks
like from the analyzer: the production bridge must keep the socket open
(`so-timeout-seconds` ≈ 3600) or sites will see this churn. Consistent with LIS-265.
