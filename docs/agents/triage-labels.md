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

```bash
plane-axi wi update LIS-NN --state ready-for-agent
```

State *names* from the "Plane state name" column resolve automatically — no manual
ID lookup. (`python3 scripts/plane_issue.py update LIS-NN --state ready-for-agent`
resolves names too, if you're already in the script flow.)

## Setup required

These five states must **exist** in your Plane project. Either:

- Create them in Plane (Project Settings → States), naming and grouping them per the table
  above, **or**
- Edit the middle two columns to point at states you already use (e.g. map
  `ready-for-human` → your existing `Todo` state).

Until the states exist, transitions will fail to resolve. Run
`plane-axi state list` to see what's currently defined.
