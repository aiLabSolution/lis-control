# Triage Labels → Plane States

The skills speak in terms of five canonical triage roles. In this repo, those roles are
realised as Plane **workflow states** (not labels), per the decision recorded in
`CLAUDE.md`. This file maps each role to the Plane state the skills should transition an
issue into.

| Canonical role    | Plane state name  | Suggested state group | Meaning                                  |
| ----------------- | ----------------- | --------------------- | ---------------------------------------- |
| `needs-triage`    | `needs-triage`    | backlog               | Maintainer needs to evaluate this issue  |
| `needs-info`      | `needs-info`      | unstarted             | Waiting on reporter for more information |
| `ready-for-agent` | `ready-for-agent` | unstarted             | Fully specified, ready for an AFK agent  |
| `ready-for-human` | `ready-for-human` | unstarted             | Requires human implementation            |
| `wontfix`         | `wontfix`         | cancelled             | Will not be actioned                     |

## How to apply

The triage skill transitions an issue by **setting its state**, not by adding a label:

1. Resolve the state ID: `plane states -p PROJECT_ID -f json`, match by the "Plane state
   name" column above.
2. Transition: `plane issues update -p PROJECT_ID ISSUE_ID --state STATE_ID`.

## Setup required

These five states must **exist** in your Plane project. Either:

- Create them in Plane (Project Settings → States), naming and grouping them per the table
  above, **or**
- Edit the middle two columns to point at states you already use (e.g. map
  `ready-for-human` → your existing `Todo` state).

Until the states exist, transitions will fail to resolve. Run
`plane states -p PROJECT_ID -f json` to see what's currently defined.
