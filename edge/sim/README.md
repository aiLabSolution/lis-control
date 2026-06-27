# Analyzer simulator harness (`edge/sim`)

> LIS-9 / S0.7 — Stage 0 deliverable. The component-test substrate that **replays
> captured analyzer messages** against the pipeline (verification pyramid level 2,
> `LIS_IMPLEMENTATION_PLAN.md` §1). Decision record:
> [`docs/adr/0004-analyzer-simulator-harness-and-conformance-fixtures.md`](../../docs/adr/0004-analyzer-simulator-harness-and-conformance-fixtures.md).

## What this is (and isn't)

- **Is:** a small, dependency-free Python harness that loads versioned
  **conformance fixtures** (a captured message + a validated manifest) and replays
  them through a pluggable **transport**, asserting a byte-faithful round-trip.
  Ships the identity **loopback** transport and the **MLLP** transport
  (`0x0B <msg> 0x1C 0x0D` frame/de-frame + HL7 `ACK^R01`, LIS-13 / S1.1). Parses a
  tolerant **HL7 v2 `ORU^R01`** and **normalizes** each observation to a
  LOINC/UCUM intermediate row (vendor code → LOINC, vendor unit → UCUM,
  LIS-14 / S1.2).
- **Isn't:** a production driver or a persistence layer. The normalized
  intermediate row is in-memory; persisting it to the core append-only Result
  store is the next slice (S1.3 / LIS-15). The ASTM E1381 codec (LIS-23 / S2.1) is
  its own slice — it plugs into the same `Transport` interface / fixture contract.

Fixtures are the **contract**: language-neutral (raw bytes + JSON manifest), so the
production driver — whatever language the S1.0 substrate decision picks — consumes
the same files this Python harness does. ADRs:
[`0005-mllp-framing-and-ack-modes.md`](../../docs/adr/0005-mllp-framing-and-ack-modes.md) (MLLP/ACK),
[`0011-oru-parse-and-normalization.md`](../../docs/adr/0011-oru-parse-and-normalization.md) (ORU parse + LOINC/UCUM normalization).

## Layout

```
edge/sim/
  pyproject.toml            # uv project; pytest dev-group; src/ layout
  src/edge_sim/
    fixtures.py             # Fixture model + loader + manifest validation
    transport.py            # Transport ABC + LoopbackTransport + MllpTransport
    mllp.py                 # MLLP wire codec: frame/deframe + streaming MllpDecoder
    ack.py                  # HL7 v2 ACK^R01 builder (original + enhanced modes)
    hl7.py                  # tolerant HL7 v2 parser: segments/fields/components + escapes (S1.2)
    oru.py                  # ORU^R01 -> typed RawObservations (PID/OBR/OBX) (S1.2)
    normalize.py            # vendor code -> LOINC, unit -> UCUM -> NormalizedObservation (S1.2)
    replay.py               # replay(fixture, transport) -> ReplayResult
    _schema.py              # tiny stdlib JSON-Schema validator (no deps)
    cli.py / __main__.py    # `edge-sim list | validate | replay | ack | normalize`
  tests/                    # pytest: schema, fixtures, transport, mllp, ack, replay, cli, hl7, oru+normalize
  fixtures/
    schema/fixture.schema.json   # canonical, cross-language manifest contract
    _example/                    # synthetic seed proving the replay self-test
    example-mllp-oru-r01/        # synthetic ORU^R01 over MLLP (S1.1)
    rayto-rac050-oru-r01/        # synthetic RAC-050 ORU^R01 w/ local codes + expected normalized rows (S1.2)
```

## Run

```bash
cd edge/sim
uv run pytest -q                       # unit tests + the replay self-test
uv run edge-sim list                   # list discovered fixtures
uv run edge-sim validate               # validate every manifest
uv run edge-sim replay example-hl7v2-oru-r01
uv run edge-sim replay example-mllp-oru-r01 --transport mllp   # round-trip over MLLP framing
uv run edge-sim ack example-mllp-oru-r01                       # the ACK^R01 the listener returns
uv run edge-sim normalize rayto-rac050-oru-r01                 # parse ORU^R01 -> normalized LOINC/UCUM rows
```

CI runs the same `pytest` on every change under `edge/sim/`
(`.github/workflows/edge-sim.yml`).

## Adding a fixture (per-analyzer supported checklist, step ②)

1. `mkdir fixtures/<vendor>-<model>-<message>/`.
2. Drop the raw captured bytes as a file (the application payload only — **no** wire
   framing; the transport applies that).
3. Write `manifest.json` per `fixtures/schema/fixture.schema.json`; set
   `synthetic: false` and a real `source.reference` (manual section or capture id)
   for genuine captures.
4. `uv run edge-sim validate` then `uv run pytest -q` — the replay self-test now
   covers the new fixture.

See [`fixtures/README.md`](fixtures/README.md) for the manifest fields.
