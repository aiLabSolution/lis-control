# Issue tracker: Plane.so

Issues and PRDs for this repo live in **Plane.so**. Drive Plane with the bundled `plane`
CLI (from the `$plane` Codex skill or `/plane` Claude skill) — **not** `gh`.

## CLI

The CLI is bundled with the user-level Plane skill. Always invoke it with an absolute
path. Codex installs it under `~/.agents/skills`; Claude uses `~/.claude/skills`:

```bash
python3 "$(readlink -f ~/.agents/skills/plane)/scripts/plane" <command> [-f json]
# Claude compatibility:
python3 "$(readlink -f ~/.claude/skills/plane)/scripts/plane" <command> [-f json]
```

Use `-f json` whenever you need to parse output (e.g. to extract an ID); omit it when
showing results to a human.

Requires two env vars: `PLANE_API_KEY` (personal access token) and `PLANE_WORKSPACE`
(workspace slug — the part after `plane.so/`; `PLANE_WORKSPACE_SLUG` is accepted as an
alias). `PLANE_BASE_URL` is optional for self-hosted instances. If either is missing the
CLI prints a helpful error — relay it, don't guess. Mutating commands print their `✓`
banner to stderr, so `-f json` output pipes cleanly.

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
python3 scripts/slice.py show LIS-26           # cheap ticket read: header + body + last comments (--json)
python3 scripts/slice.py claim LIS-26 --task "ASTM channel thread"  # assign (taken flag) + TTL'd claim record
python3 scripts/slice.py claim LIS-26 --task "..." --start   # …and transition to In Progress in one go
python3 scripts/slice.py status LIS-26 --json  # who holds what, and is the claim still live
python3 scripts/slice.py heartbeat LIS-26      # extend my claim while I keep working (task carries over)
python3 scripts/slice.py release LIS-26        # drop claim + unassign (unless another live claim remains)
```

It reads the same env + `.claude/plane-context.json` as the `plane` CLI; agent identity
defaults to `$CLAUDE_CODE_SESSION_ID`. `LIS-NN → UUID` lookups go through a per-checkout
cache (`.claude/slice-cache.json`, gitignored), so `status`/`heartbeat` don't re-scan the
backlog every loop iteration. Coordination model in `slice-loop.md`.

**Why not raw `plane issues list --state …`?** The Plane API **silently ignores** the
server-side `state`/`assignee` query params and returns `state` as a bare UUID. The
bundled CLI now compensates (client-side filters, cursor pagination), but it still pulls
the full ~30-field dump into context — `slice.py` trims subprocess-side (`?fields=` /
`?expand=state`) and orders by stage (the `[S<n>.<m>]` title prefix) so the *startable*
work surfaces first at ~1/30th the tokens.

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
  Why not `plane issues create --description`? Its `--description` is a single shell arg and
  the bundled CLI wraps whatever you pass in one HTML-escaped `<p>`, so a multi-line PRD
  collapses into one run-on paragraph — that friction is why bodies used to be dumped into a
  comment, leaving every issue with an empty description. `plane_issue.py` wraps the Plane API
  directly (like `scripts/slice.py`) and renders real HTML. **Reserve comments for the running
  progress log and the claim ledger — never the issue body.** For a title-only stub or a
  field-only tweak, `plane issues create`/`update` is still fine.
- **Read an issue**: `python3 scripts/slice.py show LIS-NN` — header + body (rendered back to
  text) + the last few comments in one cheap call. For the raw full dump,
  `plane issues get -p PROJECT_ID ISSUE_ID` plus
  `plane comments list -p PROJECT_ID -i ISSUE_ID --all` still work.
- **Update an issue body / fields**:
  `python3 scripts/plane_issue.py update LIS-NN [--body-file b.md] [--name "…"]
  [--priority high] [--state "In Progress"]` (markdown → `description_html`; state by name).
- **List issues**: `plane issues list -p PROJECT_ID [--state ID-or-name] [--priority high]
  [--assignee ID]` (add `-f json` to parse; filters run client-side, results are paginated) —
  but for "what's ready" use `scripts/slice.py next`, which is ~30× cheaper in context.
- **Comment**: for the progress log (markdown),
  `printf '%s' "$NOTE" | python3 scripts/plane_issue.py comment LIS-NN --body-file -`;
  for a quick one-liner, `plane comments add -p PROJECT_ID -i ISSUE_ID "..."`.
- **Sub-items**: `python3 scripts/plane_issue.py create --name "..." --parent LIS-NN`
  (or `plane issues create -p PROJECT_ID --name "..." --parent PARENT_UUID`).
- **Transition triage state**: `python3 scripts/plane_issue.py update LIS-NN --state
  ready-for-agent` — state *names* resolve automatically. See `triage-labels.md` for the
  role → state mapping.

Resolve names to IDs as needed: states → `plane states -p PROJECT_ID -f json`,
members → `plane members -f json`, projects → `plane projects list -f json`,
issues → `plane issues search "query" -f json`. Cache within a conversation.

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
to parse). Fall back to `plane issues get` + `plane comments list ... --all` only if you
need raw fields the compact view omits.

## When a skill says "apply a triage label"

This repo has **no orthogonal triage labels** — triage roles are realised as Plane
workflow **states**. Transition the issue's state per `triage-labels.md`.
