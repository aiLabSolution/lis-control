# Issue tracker: Plane.so

Issues and PRDs for this repo live in **Plane.so**. Drive Plane with the bundled `plane`
CLI (from the `/plane` skill) — **not** `gh`.

## CLI

The CLI is bundled at `~/.claude/skills/plane/scripts/plane`. Always invoke it with the
absolute path; resolve it via `readlink -f ~/.claude/skills/plane`:

```bash
python3 "$(readlink -f ~/.claude/skills/plane)/scripts/plane" <command> [-f json]
```

Use `-f json` whenever you need to parse output (e.g. to extract an ID); omit it when
showing results to a human.

Requires two env vars: `PLANE_API_KEY` (personal access token) and `PLANE_WORKSPACE`
(workspace slug — the part after `plane.so/`). `PLANE_BASE_URL` is optional for
self-hosted instances. If either is missing the CLI prints a helpful error — relay it,
don't guess.

## Project context

The active Plane project (and optionally issue) for this repo is stored in
`.claude/plane-context.json` (`project_id`, `project_name`, `issue_id`, `issue_title`).
Read it to get `PROJECT_ID`. If it's missing, ask the user which Plane project LIS issues
belong to (`plane projects list -f json`), then write it.

## Finding & claiming the next slice — use `scripts/slice.py`

`scripts/slice.py` is the **cheap, structured front door** to the tracker for agents. It
digests the Plane API *inside the subprocess* (via `?fields=`/`?expand=`) so only a tiny,
already-filtered, already-sorted result reaches context — **~800 tokens** instead of the
**~28k** a raw `issues list -f json` dump costs. Prefer it over `plane issues list` for the
loop (`docs/agents/slice-loop.md`).

```bash
python3 scripts/slice.py next                  # ready-for-agent ∧ unassigned, grouped by stage, priority-sorted
python3 scripts/slice.py next --stage S2 --json
python3 scripts/slice.py claim LIS-26 --task "ASTM channel thread"  # assign (taken flag) + TTL'd claim record
python3 scripts/slice.py status LIS-26         # who holds what, and is the claim still live
python3 scripts/slice.py heartbeat LIS-26      # extend my claim while I keep working
python3 scripts/slice.py release LIS-26        # drop claim + unassign (done / blocked / handoff)
```

It reads the same env + `.claude/plane-context.json` as the `plane` CLI; agent identity
defaults to `$CLAUDE_CODE_SESSION_ID`. Coordination model in `slice-loop.md`.

**Why not raw `plane issues list --state …`?** The Plane API **silently ignores** the
server-side `state` and `assignee` query params (it returns the whole backlog) and returns
`state` as a bare UUID — so the raw path forces a full dump + a second `states` fetch + an
in-context UUID→name join + manual filtering. `slice.py` does all that subprocess-side and
orders by stage (the `[S<n>.<m>]` title prefix) so the *startable* work surfaces first.

## Conventions

- **Create an issue**: `plane issues create -p PROJECT_ID --name "..." [--priority high] [--label ID] [--parent ID]`.
  The create command takes a title only — for a multi-line PRD/issue body, create the
  item with a descriptive title, then post the full body as the first comment via
  `plane comments add`.
- **Read an issue**: `plane issues get -p PROJECT_ID ISSUE_ID`, plus
  `plane comments list -p PROJECT_ID -i ISSUE_ID --all` for the conversation.
- **List issues**: `plane issues list -p PROJECT_ID [--state ID] [--priority high] [--assignee ID]`
  (add `-f json` to parse). ⚠ `--state`/`--assignee` are **ignored by the Plane API** (the
  whole backlog comes back) — for "what's ready" use `scripts/slice.py next`, not this.
- **Comment**: `plane comments add -p PROJECT_ID -i ISSUE_ID "..."`.
- **Sub-items**: `plane issues create -p PROJECT_ID --name "..." --parent PARENT_ID`.
- **Transition triage state**: resolve the state ID with `plane states -p PROJECT_ID -f json`,
  then `plane issues update -p PROJECT_ID ISSUE_ID --state STATE_ID`. See
  `triage-labels.md` for the role → state mapping.

Resolve names to IDs as needed: states → `plane states -p PROJECT_ID -f json`,
members → `plane members -f json`, projects → `plane projects list -f json`,
issues → `plane issues search "query" -f json`. Cache within a conversation.

## When a skill says "publish to the issue tracker"

Create a Plane work item in the active project — title from the issue/PRD heading, full
body as the item's first comment.

## When a skill says "fetch the relevant ticket"

Run `plane issues get -p PROJECT_ID ISSUE_ID` plus `plane comments list ... --all`.

## When a skill says "apply a triage label"

This repo has **no orthogonal triage labels** — triage roles are realised as Plane
workflow **states**. Transition the issue's state per `triage-labels.md`.
