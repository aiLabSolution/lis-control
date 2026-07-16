# AGENTS.md - Codex instructions for lis-control

## Project shape

`lis-control` is the umbrella/control-plane repository for the LIS programme. It
holds planning, architecture, diagrams, compliance docs, agent/issue-tracker
configuration, and git submodule pins. It is not the OpenELIS application repo
itself.

Current component mounts:

- `core/openelis/` - OpenELIS Global clinical core submodule.
- `edge/drivers/` - analyzer bridge/interface engine submodule.
- `edge/sim/` - umbrella-side Python simulator harness and fixtures.

Always treat submodules as independent repositories. A change inside a submodule
usually needs a component-repo commit/PR first, then an umbrella commit that bumps
the submodule pin.

## Read first

For any task, start with the smallest relevant set:

1. `README.md` for the umbrella layout.
2. `CONTEXT-MAP.md` for the relevant component context.
3. The matching `contexts/<component>/CONTEXT.md` and ADRs under
   `docs/adr/` or `contexts/<component>/docs/adr/`.
4. `docs/agents/slice-loop.md` if working a Plane slice.
5. The nested agent file for the component you enter, especially
   `core/openelis/AGENTS.md` when editing `core/openelis/`.

Root `CLAUDE.md` contains the same umbrella workflow for Claude sessions. This
file is the Codex entry point; prefer keeping durable, tool-agnostic guidance
here and component-specific guidance in the nested component docs.

## Repository skills and custom agents

Codex discovers the project skills under `.agents/skills/`:

- `$bench-capture` - route analyzer bench sessions to the correct capture tool and runbook.
- `$core-verify` - run OpenELIS core and analyzer-bridge Java verification through Docker Maven.
- `$pin-bump` - land component changes through the component-to-umbrella pin chain.
- `$work-slice` - execute a Plane slice from claim through review, teardown, and release.

Codex custom agents live under `.codex/agents/`:

- `adversarial-reviewer` - hostile pre-merge review gate; use for slice PRs.
- `ac-verifier` - verify every acceptance criterion before closing a slice.
- `findings-triager` - disposition review backlogs; report-only unless issue creation is explicit.
- `pin-auditor` - audit `origin/main` submodule pin reachability, ancestry, lag, and checkout drift.

When a workflow calls for one of these custom agents, spawn it by its exact name and
pass the slice key, worktree, diff range or PR, and acceptance criteria it needs. Let
the agent use the model and reasoning settings in its TOML definition.

## Workflow rules

- Do not commit directly on `main`, and do not push `origin main`.
- Use a dedicated worktree per Plane slice:
  `../lis-control-<key>` on branch `<key>-<slug>`.
- Do not switch the shared primary checkout away from its current branch.
- Before editing a slice, check/claim it with
  `python3 scripts/slice.py status LIS-NN` and
  `python3 scripts/slice.py claim LIS-NN --task "..." [--start]`; use `heartbeat`
  for long work and `release` on handoff, done, or blocked.
- Use `scripts/slice.py next` for ready work and `scripts/slice.py show LIS-NN`
  to read a ticket. Do not use a raw `plane issues list` dump as the front
  door; the repo docs call out API filtering issues.
- Issue bodies and markdown progress comments go through
  `scripts/plane_issue.py` (`create` / `update` / `comment`) — state names and
  `LIS-NN` keys are accepted; priorities are the API's string enum.
- Coordinate through the Plane issue and branch. Fetch/rebase before commits,
  push after commits, and never force-push a shared slice branch.
- Treat CI as repository-local and non-transitive. Before merging a component
  PR, verify the expected checks are green on that exact PR head; checkout,
  authentication, and submodule failures still block even when tests never
  start. Local targeted tests and green umbrella workflows supplement component
  CI but never replace it. Do not merge or pin a red component PR merely because
  GitHub permits the merge.
- Keep `.claude/plane-context.json` and other per-checkout bookkeeping out of
  substantive diffs.
- If you touch a submodule, keep the submodule commit and the umbrella pin bump
  as separate, explicit steps.

## Command map

Run commands from the directory shown.

Umbrella scripts:

```bash
python3 -m unittest discover -s scripts -p 'test_*.py' -v
```

Edge simulator:

```bash
cd edge/sim
uv run --frozen --python 3.12 pytest -q
```

OpenELIS core backend:

```bash
cd core/openelis
mvn spotless:apply
mvn clean install -DskipTests -Dmaven.test.skip=true
```

OpenELIS frontend:

```bash
cd core/openelis/frontend
npm run format
npm run check-format
npm run test
npm run pw:test
```

Use `npm run pw:*` scripts for Playwright. Do not add new Cypress tests unless
the user explicitly asks for maintenance of existing Cypress coverage.

Core bootstrap health is CI-backed and Docker-heavy:

```bash
docker compose --project-directory core/openelis \
  -f core/openelis/docker-compose.yml \
  -f core/openelis/build.docker-compose.yml \
  -f core/openelis/.github/ci/ci.memory-limits.yml \
  up -d --build
bash deploy/ci/healthcheck.sh
```

Only run this locally when the task requires a full boot check and Docker is
available.

## Domain constraints

- Use the vocabulary from the relevant `CONTEXT.md`; do not rename domain
  concepts casually.
- Surface any contradiction with an ADR instead of silently overriding it.
- For OpenELIS changes, follow `core/openelis/AGENTS.md`: Java 21, Spring MVC
  rather than Spring Boot for the core, React 17 + Carbon, React Intl for
  user-facing strings, JUnit 4 for backend tests, Liquibase for schema changes,
  and service-layer transaction boundaries.
- For FILE-based analyzer workflows, bridge owns directory watching/polling and
  file transport; OpenELIS owns configuration, bridge registration, direct
  ingestion endpoint, and result processing.

## Codex-specific notes

- Prefer `rg`/`rg --files` for searches.
- Expect permission-denied noise under generated or runtime volumes such as
  `core/openelis/volume/lucene`; avoid treating that as a repo failure.
- Keep edits scoped to the repo layer being worked on: umbrella docs/config at
  root, component code inside the relevant submodule, and context docs under
  `contexts/`.
- If Plane credentials or the bundled Plane CLI are unavailable, report the
  missing requirement and continue with local code/docs work when possible.
