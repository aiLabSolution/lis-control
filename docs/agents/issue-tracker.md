# Issue tracker: Plane.so

Issues and PRDs for this repo live in **Plane.so**. Drive Plane with the **`plane-axi`**
CLI (https://github.com/aiLabSolution/plane-axi — the `/plane-axi` Claude skill /
`$plane-axi` Codex skill, tracked in-repo under `.claude/skills/` and `.agents/skills/`)
— **not** `gh`, and not the retired bundled `plane` skill CLI.

## CLI

`plane-axi` is installed on PATH (mise npm global). If it is missing, run the same
arguments through `npx -y github:ailabsolution/plane-axi`, or install it with
`npm i -g github:ailabsolution/plane-axi`.

```bash
plane-axi <command> [flags]      # e.g. plane-axi wi view LIS-26
plane-axi <command> --help       # complete flags + examples per command
```

Output is compact TOON on stdout — parse it directly; there is no `-f json` flag. The
CLI never prompts and returns structured errors. It requires two env vars:
`PLANE_API_KEY` (personal access token) and `PLANE_WORKSPACE` (workspace slug — the part
after `plane.so/`; `PLANE_WORKSPACE_SLUG` is accepted as an alias). `PLANE_BASE_URL` is
optional for self-hosted instances. If either is missing the CLI prints a structured
error with the fix — relay it, don't guess.

## Project context

Readable refs like `LIS-26` resolve their project from the identifier prefix, so
work-item commands usually need no project setup. Project-scoped commands (`wi list`,
`wi create`, `state list`, `label list`, `cycle …`, `module …`) take `--project LIS`, or
a per-checkout default selected once with `plane-axi use LIS` (stored in
`.plane-axi.json`, gitignored).

The Python front-door scripts below read `.claude/plane-context.json`
(`project_id`, `project_name`, `issue_id`, `issue_title`) instead. Both files are
per-checkout bookkeeping — keep their churn out of substantive diffs.

## Finding & claiming the next slice — use `scripts/slice.py`

`scripts/slice.py` is the **cheap, structured front door** to the tracker for agents. It
digests the Plane API *inside the subprocess* (via `?fields=`/`?expand=`) so only a tiny,
already-filtered, already-sorted result reaches context — **~800 tokens**. Prefer it over
`plane-axi wi list` for the loop (`docs/agents/slice-loop.md`).

```bash
python3 scripts/slice.py next                  # ready-for-agent ∧ unassigned, grouped by stage, priority-sorted
python3 scripts/slice.py next --stage S2 --json
python3 scripts/slice.py show LIS-26           # cheap ticket read: header + body + last comments (--json)
python3 scripts/slice.py claim LIS-26 --task "ASTM channel thread"  # assign (taken flag) + TTL'd claim record
python3 scripts/slice.py claim LIS-26 --task "..." --start   # …and transition to In Progress in one go
python3 scripts/slice.py status LIS-26 --json  # who holds what, and is the claim still live
python3 scripts/slice.py heartbeat LIS-26      # extend my claim while I keep working (task carries over)
python3 scripts/slice.py release LIS-26        # drop claim + unassign (unless another live claim remains)
```

It reads the same env as `plane-axi` plus `.claude/plane-context.json`; agent identity
defaults to `$CLAUDE_CODE_SESSION_ID`. `LIS-NN → UUID` lookups go through a per-checkout
cache (`.claude/slice-cache.json`, gitignored), so `status`/`heartbeat` don't re-scan the
backlog every loop iteration. Coordination model in `slice-loop.md`.

**Why not `plane-axi wi list` for the loop?** Its output is compact (default fields
`seq,title,state,priority`, 50-row default), so it's fine for ad-hoc queries — but it has
no stage grouping (the `[S<n>.<m>]` title prefix), no ready-for-agent ∧ unassigned
pre-filter, and no view of the claim ledger. `slice.py next` surfaces the *startable*
work first, and `slice.py claim`/`status`/`heartbeat`/`release` are the race-safe
coordination protocol — there is no `plane-axi` equivalent.

## Conventions

- **Create an issue (with a body)**: use `scripts/plane_issue.py` — it renders the markdown
  body into the work item's **description** (where it belongs), not a comment. The body comes
  from a file or stdin, so multi-line markdown is easy:
  ```bash
  python3 scripts/plane_issue.py create --name "[S2.4] ERBA EC90 channel thread" \
      --body-file slice.md [--priority high] [--parent LIS-22] [--state ready-for-agent]
  printf '%s' "$BODY" | python3 scripts/plane_issue.py create --name "..." --body-file -
  python3 scripts/plane_issue.py render --body-file slice.md   # preview the HTML, no network
  ```
  `--state` takes a state UUID **or name**, `--parent` takes `LIS-NN` or a UUID, and
  `--priority` is the API's string enum (`urgent|high|medium|low|none`).
  Why not `plane-axi wi create --body`? Its `--body` is a single plain-text shell arg that
  the CLI wraps in **one HTML `<p>`**, so a multi-line PRD collapses into one run-on
  paragraph — the same flaw the retired CLI had. `plane_issue.py` wraps the Plane API
  directly (like `scripts/slice.py`) and renders real HTML. **Reserve comments for the
  running progress log and the claim ledger — never the issue body.** For a title-only
  stub or a field-only tweak, `plane-axi wi create`/`update` is fine.
- **Read an issue**: `python3 scripts/slice.py show LIS-NN` — header + body (rendered back to
  text) + the last few comments in one cheap call. For the raw view,
  `plane-axi wi view LIS-NN` (add `--full` only if the body is truncated) plus
  `plane-axi comment list LIS-NN --all`.
- **Update an issue body / fields**:
  `python3 scripts/plane_issue.py update LIS-NN [--body-file b.md] [--name "…"]
  [--priority high] [--state "In Progress"]` (markdown → `description_html`; state by name).
  For field-only tweaks, `plane-axi wi update LIS-NN [--title "…"] [--priority high]
  [--state "In Progress"]` — state names resolve subprocess-side.
- **List issues**: `plane-axi wi list [--state <name|group>] [--priority high]
  [--assignee <email>] [--fields seq,title,state] [--limit N | --all]` — but for "what's
  ready" use `scripts/slice.py next`, which is stage-ordered and claim-aware.
- **Comment**: for the progress log (markdown),
  `printf '%s' "$NOTE" | python3 scripts/plane_issue.py comment LIS-NN --body-file -`;
  for a quick one-liner, `plane-axi comment add LIS-NN --body "..."` (plain text in one
  `<p>` — markdown does not render).
- **Sub-items**: `python3 scripts/plane_issue.py create --name "..." --parent LIS-NN`
  (or `plane-axi wi create --title "..." --parent LIS-NN`).
- **Transition triage state**: `plane-axi wi update LIS-NN --state ready-for-agent` —
  state *names* resolve automatically. See `triage-labels.md` for the role → state mapping.
- **Search**: `plane-axi wi search "query" [--limit N | --all]` — workspace-wide,
  matched against titles and bodies. Also: `plane-axi wi assign LIS-NN <member>` (member
  by UUID, name, or email), `plane-axi wi close LIS-NN`, and `plane-axi wi delete LIS-NN
  --yes` (deletion always requires the explicit `--yes`).

Resolve names to IDs as needed: states → `plane-axi state list`, members →
`plane-axi member list`, projects → `plane-axi project list`, labels →
`plane-axi label list`. Refs accept UUIDs, identifiers, exact names, or emails and are
resolved subprocess-side. For an endpoint the command surface doesn't cover,
`plane-axi api <METHOD> <path> [--input <json>]` is the last-resort escape hatch.

## When a skill says "publish to the issue tracker"

Create a Plane work item in the active project — **title → the work item name, full body →
the work item description** (markdown rendered to HTML):

```bash
python3 scripts/plane_issue.py create --name "<issue/PRD heading>" --body-file <body.md>
```

Do **not** put the body in a comment — comments are for the progress log and the claim ledger.
If the skill wants the issue **ready for an AFK agent**, set its triage state too — triage is
realised as a Plane **state**, not a label (see `triage-labels.md`): pass
`--state ready-for-agent` to `create` (state names resolve automatically).

## When a skill says "fetch the relevant ticket"

Run `python3 scripts/slice.py show LIS-NN` (add `--comments 10` for more history, `--json`
to parse). Fall back to `plane-axi wi view LIS-NN --full` +
`plane-axi comment list LIS-NN --all` only if you need raw fields the compact view omits.

## When a skill says "apply a triage label"

This repo has **no orthogonal triage labels** — triage roles are realised as Plane
workflow **states**. Transition the issue's state per `triage-labels.md`.
