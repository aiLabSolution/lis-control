---
name: plane-axi
description: Manage Plane.so projects, work items, comments, cycles, modules, labels, states, and members from an agent-friendly CLI.
---

# Plane AXI

Use this skill when the user asks to inspect or change Plane.so project-management data. The CLI emits compact TOON on stdout, never prompts, and returns structured errors.

## Setup

Set `PLANE_API_KEY` and `PLANE_WORKSPACE` (or `PLANE_WORKSPACE_SLUG`). `plane-axi` is installed on PATH (mise npm global); if it is missing, run the same arguments through `npx -y github:ailabsolution/plane-axi`, or install it with `npm i -g github:ailabsolution/plane-axi`. Run `plane-axi` with no arguments for a live directory-scoped dashboard. Select a default project with `plane-axi use <project>`, or pass `--project <project>`.

In this repo, `docs/agents/issue-tracker.md` is the authority on when to use `plane-axi` versus the repo's Python front door (`scripts/slice.py` for the slice loop and claim ledger, `scripts/plane_issue.py` for rendered-markdown bodies and comments).

## Commands

### project

- `plane-axi project list` — List workspace projects
- `plane-axi project view <ref>` — Show a project
- `plane-axi project create --name <name> --identifier <id>` — Create a project

### use

- `plane-axi use <project>` — Select the directory-scoped default project

### me

- `plane-axi me` — Show the authenticated Plane user

### wi

- `plane-axi wi list [flags]` — List work items
- `plane-axi wi view <ref> [--full]` — Show a work item
- `plane-axi wi create --title <title> [flags]` — Create a work item
- `plane-axi wi update <ref> [flags]` — Update a work item
- `plane-axi wi assign <ref> <member>...` — Replace work item assignees
- `plane-axi wi close <ref>` — Move a work item to the first completed state
- `plane-axi wi delete <ref> --yes` — Delete a work item
- `plane-axi wi search <query> [--limit <n>|--all]` — Search work items across the workspace

### comment

- `plane-axi comment list <wi-ref> [--all]` — List comments or all activity
- `plane-axi comment add <wi-ref> (--body <text>|--body-file <path>)` — Add a comment

### cycle

- `plane-axi cycle list [--project <ref>]` — List project cycles
- `plane-axi cycle view <ref>` — Show a cycle
- `plane-axi cycle create --name <name> [flags]` — Create a cycle

### module

- `plane-axi module list [--project <ref>]` — List project modules
- `plane-axi module view <ref>` — Show a module
- `plane-axi module create --name <name> [flags]` — Create a module

### state

- `plane-axi state list [--project <ref>]` — List project workflow states

### label

- `plane-axi label list [--project <ref>]` — List project labels

### member

- `plane-axi member list` — List workspace members

### api

- `plane-axi api <METHOD> <path> [--input <json>]` — Call a Plane API path directly

### setup

- `plane-axi setup [--app <app>] [--scope <scope>] [--skill]` — Install session hooks or the generated skill

## Operating rules

- Prefer readable references such as `LIS-42`; UUIDs are also accepted.
- Run a command with `--help` for its complete flags and examples.
- Use `--full` only when a truncated work-item body needs expansion.
- Work-item deletion requires explicit `--yes`.
- `--body` on `wi create`/`wi update`/`comment add` is plain text wrapped in a single HTML paragraph — for multi-line markdown bodies or comments use `scripts/plane_issue.py` instead (see `docs/agents/issue-tracker.md`).
- Use `plane-axi api <METHOD> <path>` only when the normal command surface does not cover the endpoint.
