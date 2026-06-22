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

## Conventions

- **Create an issue**: `plane issues create -p PROJECT_ID --name "..." [--priority high] [--label ID] [--parent ID]`.
  The create command takes a title only — for a multi-line PRD/issue body, create the
  item with a descriptive title, then post the full body as the first comment via
  `plane comments add`.
- **Read an issue**: `plane issues get -p PROJECT_ID ISSUE_ID`, plus
  `plane comments list -p PROJECT_ID -i ISSUE_ID --all` for the conversation.
- **List issues**: `plane issues list -p PROJECT_ID [--state ID] [--priority high] [--assignee ID]`
  (add `-f json` to parse).
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
