# Analyzer simulator harness (`edge/sim`)

> LIS-9 / S0.7 — Stage 0 deliverable. The component-test substrate that **replays
> captured analyzer messages** against the pipeline (verification pyramid level 2,
> `LIS_IMPLEMENTATION_PLAN.md` §1). Decision record:
> [`docs/adr/0004-analyzer-simulator-harness-and-conformance-fixtures.md`](../../docs/adr/0004-analyzer-simulator-harness-and-conformance-fixtures.md).

## What this is (and isn't)

- **Is:** a small, dependency-free Python harness that loads versioned
  **conformance fixtures** (a captured message + a validated manifest) and replays
  them through a pluggable **transport**, asserting a byte-faithful round-trip.
- **Isn't:** a protocol implementation. MLLP framing (LIS-13 / S1.1) and the ASTM
  E1381 codec (LIS-23 / S2.1) are later slices — they plug into the `Transport`
  interface here. This skeleton ships only the identity **loopback** transport.

Fixtures are the **contract**: language-neutral (raw bytes + JSON manifest), so the
production driver — whatever language the S1.0 substrate decision picks — consumes
the same files this Python harness does.

## Layout

```
edge/sim/
  pyproject.toml            # uv project; pytest dev-group; src/ layout
  src/edge_sim/
    fixtures.py             # Fixture model + loader + manifest validation
    transport.py            # Transport ABC + LoopbackTransport
    replay.py               # replay(fixture, transport) -> ReplayResult
    _schema.py              # tiny stdlib JSON-Schema validator (no deps)
    cli.py / __main__.py    # `edge-sim list | validate | replay`
  tests/                    # pytest: schema, fixtures, transport, replay, cli
  fixtures/
    schema/fixture.schema.json   # canonical, cross-language manifest contract
    _example/                    # synthetic seed proving the replay self-test
```

## Run

```bash
cd edge/sim
uv run pytest -q                       # unit tests + the replay self-test
uv run edge-sim list                   # list discovered fixtures
uv run edge-sim validate               # validate every manifest
uv run edge-sim replay example-hl7v2-oru-r01
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
