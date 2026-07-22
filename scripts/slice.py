#!/usr/bin/env python3
"""LIS slice harness — find, read and claim the next workable slice, cheaply.

Why this exists
---------------
Agents kept burning ~28k tokens per loop iteration just to answer "what do I work on
next?": the retired bundled `plane` CLI's `issues list -f json` returned all ~30 fields
on every work item (incl. three description variants + timestamps + UUIDs), the `state`
came back as a bare UUID that forced a *second* `states` fetch to decode, and the
server-side `--state`/`--assignee` filters are silently ignored by the Plane API — so
the agent pulled the whole backlog and filtered it in-context. Today's `plane-axi wi
list` is compact, but it still has no stage grouping, no ready-for-agent ∧ unassigned
pre-filter, and no claim-ledger view. See `docs/agents/issue-tracker.md`.

This helper does all of that **inside the subprocess** using the Plane REST API's
`?fields=` (trim) and `?expand=state` (inline the name) — so only a tiny, already-filtered,
already-sorted result reaches the agent's context (~1-2k tokens instead of ~28k). `show`
is the matching cheap *read* path for step 1 of the loop ("read the ticket"): trimmed
fields, description_html downconverted to text, and just the tail of the comments.

Coordination (single shared Plane identity)
------------------------------------------
Every agent acts through the one PAT (`marloe.uy.jr`), so an assignee can flag "taken" but
not *which* agent holds it. Two layers, per `docs/agents/slice-loop.md`:
  * coarse / cross-slice : the issue **assignee** is the "taken" flag. `next` hides assigned
    items; `claim` assigns, `release` unassigns. No extra read — assignee is in the cheap fetch.
  * fine / same-slice     : a machine-readable, append-only **claim ledger** in the comments
    (`LIS-CLAIM/HEARTBEAT/RELEASE v1 agent=<id> task=<...> until=<ISO>`) with a TTL, so
    `status` reduces the last few comments to "who holds what, and is it still alive" — no
    eyeballing timestamps, no reading the whole activity feed.
`claim` writes the ledger record *first*, then re-reads it: if a rival's live claim landed
earlier, we withdraw (first-writer-wins settles the claim/claim race). `release` keeps the
coarse assignee flag while any other agent still holds a live claim on a shared slice, so
the slice doesn't resurface in other agents' `next` mid-work.

Usage
-----
  python3 scripts/slice.py next                 # ready-for-agent ∧ unassigned, stage-ordered
  python3 scripts/slice.py next --stage S2       # only Stage 2 slices
  python3 scripts/slice.py next --json            # machine-readable (id/key/priority/stage)
  python3 scripts/slice.py show LIS-26            # cheap ticket read (+ --comments N, --json)
  python3 scripts/slice.py claim LIS-26 --task "ASTM channel thread" --ttl 120
  python3 scripts/slice.py claim LIS-26 --task "..." --start   # + transition to In Progress
  python3 scripts/slice.py status LIS-26          # current claim ownership (+ --json)
  python3 scripts/slice.py heartbeat LIS-26       # extend my claim's TTL (task carries over)
  python3 scripts/slice.py release LIS-26         # drop claim + unassign (if no other live claim)

Env: PLANE_API_KEY (required); PLANE_WORKSPACE (or PLANE_WORKSPACE_SLUG; default
"labsolution"); PLANE_PROJECT_ID (else .claude/plane-context.json, else the LIS project).
Agent identity: --agent, else LIS_AGENT_ID, else Codex/Claude session env, else host:pid.
Stdlib only; shared REST plumbing lives in scripts/planelib.py.
"""
import argparse
import json
import os
import re
import socket
import sys
from datetime import datetime, timedelta, timezone
from html import unescape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import planelib as pl  # noqa: E402

# Triage role realised as a Plane workflow state (docs/agents/triage-labels.md).
READY_STATE = "ready-for-agent"
PRIORITY_RANK = {"urgent": 0, "high": 1, "medium": 2, "low": 3, "none": 4}
CLAIM_TAG = "LIS"  # ledger line prefix: "LIS-CLAIM v1 ..."


# --------------------------------------------------------------------------- helpers
def _agent_id(explicit=None) -> str:
    return (explicit or os.environ.get("LIS_AGENT_ID")
            or os.environ.get("CODEX_THREAD_ID")
            or os.environ.get("CODEX_SESSION_ID")
            or os.environ.get("CLAUDE_CODE_SESSION_ID")
            or f"{socket.gethostname()}:{os.getpid()}")


def _stage(name: str):
    """Stage number from a '[S2.9] ...' title prefix, or None (unstaged)."""
    m = re.match(r"\s*\[S(\d+)(?:\.(\d+))?\]", name or "")
    return (int(m.group(1)), int(m.group(2) or 0)) if m else None


def _now():
    return datetime.now(timezone.utc)


def _iso(dt) -> str:
    return dt.replace(microsecond=0).isoformat()


def _ts(s: str) -> datetime:
    """created_at string -> aware datetime. The API mixes UTC offsets (+00:00 /
    +02:00) across comments, so plain string ordering is not chronological."""
    try:
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return datetime.min.replace(tzinfo=timezone.utc)


def _html_to_text(html: str) -> str:
    """description_html -> readable markdown-ish text (structure kept, tags dropped).
    Reads the html field, not description_stripped — stripped is lossy on rich bodies."""
    h = re.sub(r"<h([1-6])[^>]*>", lambda m: "\n" + "#" * int(m.group(1)) + " ", html)
    h = re.sub(r"<li[^>]*>", "\n- ", h)
    h = re.sub(r"<(?:br|hr)[^>]*>", "\n", h)
    h = re.sub(r"</(?:p|li|ul|ol|h[1-6]|blockquote|pre|div|table|tr)>", "\n", h)
    h = re.sub(r"<[^>]+>", "", h)
    return re.sub(r"\n{3,}", "\n\n", unescape(h)).strip()


# --------------------------------------------------------------------------- claim ledger
def _post_ledger(issue_id: str, verb: str, agent: str, task: str = "", until=None) -> None:
    line = f"{CLAIM_TAG}-{verb} v1 agent={agent}"
    if task:
        # Curly-quote both ASCII quote kinds so the single-quoted form always
        # round-trips through _LEDGER_RE (repr-style backslash escapes don't).
        line += " task='{}'".format(task.replace("'", "’").replace('"', "”"))
    if until is not None:
        line += f" until={_iso(until)}"
    pl.api("POST", f"/projects/{pl.project()}/work-items/{issue_id}/comments/",
           body={"comment_html": f"<p>{line}</p>"})


_LEDGER_RE = re.compile(
    rf"{CLAIM_TAG}-(CLAIM|HEARTBEAT|RELEASE)\s+v1\s+agent=(\S+)"
    r"(?:\s+task=(?:'([^']*)'|\"([^\"]*)\"|(\S+)))?"
    r"(?:\s+until=(\S+))?")


def _read_claims(issue_id: str) -> dict:
    """Reduce the last few ledger comments to current ownership per agent."""
    rows = pl.paginate(f"/projects/{pl.project()}/work-items/{issue_id}/comments/",
                       {"fields": "created_at,actor,comment_stripped", "per_page": 100})
    rows.sort(key=lambda r: _ts(r.get("created_at", "")))
    state = {}  # agent -> dict(verb, task, until, at)
    for r in rows[-40:]:  # only the tail matters
        text = r.get("comment_stripped") or ""
        for m in _LEDGER_RE.finditer(text):
            verb, agent, t1, t2, t3, until = m.groups()
            state[agent] = {"verb": verb, "task": t1 or t2 or t3 or "",
                            "until": until, "at": r.get("created_at", "")}
    live = {}
    now = _now()
    for agent, c in state.items():
        if c["verb"] == "RELEASE":
            continue
        active = True
        if c["until"]:
            try:
                dt = datetime.fromisoformat(c["until"])
                if dt.tzinfo is None:  # a hand-written naive stamp must not TypeError
                    dt = dt.replace(tzinfo=timezone.utc)
                active = dt > now
            except (ValueError, TypeError):
                active = True
        c["active"] = active
        live[agent] = c
    return live


# --------------------------------------------------------------------------- commands
def cmd_next(args) -> None:
    items = pl.items()
    ready = [it for it in items
             if pl.state_name(it) == READY_STATE
             and (args.include_claimed or not it.get("assignees"))]
    if args.stage:
        want = int(args.stage.upper().removeprefix("S"))
        ready = [it for it in ready
                 if _stage(it["name"]) and _stage(it["name"])[0] == want]

    def sort_key(it):
        st = _stage(it["name"])
        return (st[0] if st else 98, PRIORITY_RANK.get(it.get("priority"), 5),
                st[1] if st else 0, -it.get("sequence_id", 0))
    ready.sort(key=sort_key)
    if args.limit:
        ready = ready[: args.limit]

    if args.json:
        print(json.dumps([
            {"key": f"LIS-{it['sequence_id']}", "id": it["id"],
             "name": it["name"], "priority": it.get("priority", "none"),
             "stage": (_stage(it["name"]) or [None])[0],
             "claimed": bool(it.get("assignees"))}
            for it in ready], indent=2))
        return

    if not ready:
        print(f"No {READY_STATE} unclaimed slices" + (f" in stage {args.stage}." if args.stage else "."))
        return
    last = object()
    for it in ready:
        st = _stage(it["name"])
        group = f"Stage {st[0]}" if st else "(unstaged)"
        if group != last:
            print(f"\n{group}")
            last = group
        claimed = "  ⚑taken" if it.get("assignees") else ""
        print(f"  LIS-{it['sequence_id']:<3} {it.get('priority','none'):<7} "
              f"{it['name'][:72]}{claimed}")
    print(f"\n{len(ready)} slice(s). Claim one: "
          f"python3 scripts/slice.py claim LIS-<n> --task \"...\"")


def cmd_show(args) -> None:
    it = pl.resolve_item(args.key)
    full = pl.api("GET", f"/projects/{pl.project()}/work-items/{it['id']}/",
                  {"expand": "state",
                   "fields": "id,sequence_id,name,priority,state,description_html,updated_at"})
    desc = _html_to_text(full.get("description_html") or "")
    comments = []
    if args.comments:
        rows = pl.paginate(f"/projects/{pl.project()}/work-items/{it['id']}/comments/",
                           {"fields": "created_at,comment_stripped"})
        rows.sort(key=lambda r: _ts(r.get("created_at", "")))
        comments = rows[-args.comments:]
    if args.json:
        print(json.dumps({
            "key": f"LIS-{full['sequence_id']}", "id": full["id"], "name": full["name"],
            "state": pl.state_name(full), "priority": full.get("priority", "none"),
            "assigned": bool(it.get("assignees")), "description": desc,
            "comments": [{"at": r.get("created_at", ""),
                          "text": (r.get("comment_stripped") or "").strip()}
                         for r in comments]}, indent=2))
        return
    print(f"LIS-{full['sequence_id']}  {full['name']}")
    print(f"  state={pl.state_name(full)}  priority={full.get('priority', 'none')}  "
          f"assignee={'taken' if it.get('assignees') else 'free'}")
    if desc:
        print("\n" + desc)
    for r in comments:
        text = (r.get("comment_stripped") or "").strip().replace("\n", " ¶ ")
        print(f"\n  [{r.get('created_at', '')[:16]}] {text[:300]}")


def cmd_claim(args) -> None:
    it = pl.resolve_item(args.key)
    iid, agent = it["id"], _agent_id(args.agent)
    if pl.state_name(it) != READY_STATE:
        print(f"⚠ LIS-{it['sequence_id']} is '{pl.state_name(it)}', "
              f"not {READY_STATE} — claiming anyway.")
    # cooperative lock: don't stomp another agent's live claim unless --force.
    prior = {a: c for a, c in _read_claims(iid).items() if a != agent and c["active"]}
    if prior and not args.force:
        who = ", ".join(f"{a} (task={c['task'] or '—'}, until {c['until']})"
                        for a, c in prior.items())
        sys.exit(f"⚠ CONTENDED: LIS-{it['sequence_id']} already claimed by {who}. "
                 f"Take a different sub-task, or --force to share the slice "
                 f"(then partition by sub-item — see slice-loop.md).")
    until = _now() + timedelta(minutes=args.ttl)
    # Ledger first, assignee second: the append-only ledger is the tie-breaker for
    # near-simultaneous claims, and this order can't leave the issue assigned with
    # no machine-readable owner if the second write dies.
    _post_ledger(iid, "CLAIM", agent, args.task, until)
    claims = _read_claims(iid)
    mine = claims.get(agent)
    # If our own record hasn't surfaced yet, treat every rival as earlier (back off).
    mine_at = _ts(mine["at"]) if mine else datetime.max.replace(tzinfo=timezone.utc)
    rivals = {a: c for a, c in claims.items()
              if a != agent and c["active"] and _ts(c["at"]) < mine_at}
    if rivals and not args.force:
        _post_ledger(iid, "RELEASE", agent)
        sys.exit(f"⚠ LOST RACE: LIS-{it['sequence_id']} was claimed concurrently by "
                 f"{', '.join(rivals)} — withdrew my claim. Pick another slice.")
    patch = {"assignees": [pl.me()]}                        # coarse "taken" flag
    if args.start:
        patch["state"] = pl.state_id(args.start)
    pl.api("PATCH", f"/projects/{pl.project()}/work-items/{iid}/", body=patch)
    print(f"✓ claimed LIS-{it['sequence_id']} as agent={agent} until {_iso(until)}"
          + (f" — task: {args.task}" if args.task else "")
          + (f" — state → {args.start}" if args.start else ""))
    shared = rivals or prior
    if shared:
        print(f"  (shared: also held by {', '.join(shared)} — partition by sub-item.)")


def cmd_heartbeat(args) -> None:
    it = pl.resolve_item(args.key)
    agent = _agent_id(args.agent)
    mine = _read_claims(it["id"]).get(agent)
    verb = "HEARTBEAT" if mine else "CLAIM"  # no live claim to extend → this *is* a claim
    if not mine:
        print(f"⚠ no live claim by {agent} on LIS-{it['sequence_id']} — posting CLAIM instead.")
    until = _now() + timedelta(minutes=args.ttl)
    _post_ledger(it["id"], verb, agent, (mine or {}).get("task", ""), until)
    print(f"✓ {verb.lower()} LIS-{it['sequence_id']} agent={agent} until {_iso(until)}")


def cmd_release(args) -> None:
    it = pl.resolve_item(args.key)
    agent = _agent_id(args.agent)
    _post_ledger(it["id"], "RELEASE", agent)
    others = {a: c for a, c in _read_claims(it["id"]).items() if a != agent and c["active"]}
    if others:
        # Shared slice: another agent still works it — keep the coarse "taken" flag
        # so the slice doesn't resurface in other agents' `next` mid-work.
        print(f"✓ released LIS-{it['sequence_id']} "
              f"(assignee kept — live claims: {', '.join(others)})")
    elif args.keep_assignee:
        print(f"✓ released LIS-{it['sequence_id']} (assignee kept by request)")
    else:
        pl.api("PATCH", f"/projects/{pl.project()}/work-items/{it['id']}/",
               body={"assignees": []})
        print(f"✓ released LIS-{it['sequence_id']} (unassigned)")


def cmd_status(args) -> None:
    it = pl.resolve_item(args.key)
    claims = _read_claims(it["id"])
    if args.json:
        print(json.dumps({
            "key": f"LIS-{it['sequence_id']}", "id": it["id"], "name": it["name"],
            "state": pl.state_name(it), "assigned": bool(it.get("assignees")),
            "claims": [{"agent": a, "active": c["active"], "task": c["task"],
                        "until": c["until"], "verb": c["verb"].lower(), "at": c["at"]}
                       for a, c in sorted(claims.items(), key=lambda kv: _ts(kv[1]["at"]))],
        }, indent=2))
        return
    print(f"LIS-{it['sequence_id']}  {it['name'][:70]}")
    print(f"  state    : {pl.state_name(it)}")
    print(f"  assignee : {'taken' if it.get('assignees') else 'free'}")
    if not claims:
        print("  claims   : none")
        return
    for agent, c in sorted(claims.items(), key=lambda kv: _ts(kv[1]["at"])):
        flag = "ACTIVE" if c["active"] else "stale"
        print(f"  claim    : [{flag}] agent={agent} task={c['task'] or '—'} "
              f"until={c['until'] or '—'} ({c['verb'].lower()})")


def main() -> None:
    ap = argparse.ArgumentParser(prog="slice", description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    n = sub.add_parser("next", help="list ready-for-agent ∧ unassigned slices, stage-ordered")
    n.add_argument("--stage", help="restrict to a stage, e.g. S2")
    n.add_argument("--include-claimed", action="store_true", help="also show assigned slices")
    n.add_argument("--limit", type=int, help="cap the number shown")
    n.add_argument("--json", action="store_true", help="machine-readable output")
    n.set_defaults(func=cmd_next)

    s = sub.add_parser("show", help="cheap ticket read: trimmed fields + body + comment tail")
    s.add_argument("key", help="slice key, e.g. LIS-26 (or a raw UUID)")
    s.add_argument("--comments", type=int, default=5, metavar="N",
                   help="show the last N comments (default 5; 0 for none)")
    s.add_argument("--json", action="store_true", help="machine-readable output")
    s.set_defaults(func=cmd_show)

    for name, fn, hlp in [("claim", cmd_claim, "assign + post a TTL'd claim record"),
                          ("heartbeat", cmd_heartbeat, "extend my claim's TTL"),
                          ("release", cmd_release, "drop claim + unassign"),
                          ("status", cmd_status, "show current claim ownership")]:
        p = sub.add_parser(name, help=hlp)
        p.add_argument("key", help="slice key, e.g. LIS-26")
        p.add_argument("--agent", help="agent identity (default: session id / host:pid)")
        if name in ("claim", "heartbeat"):
            p.add_argument("--ttl", type=int, default=90, help="claim lifetime in minutes (default 90)")
        if name == "claim":
            p.add_argument("--task", default="", help="sub-task / files this claim covers")
            p.add_argument("--force", action="store_true",
                           help="claim even if another agent holds a live claim (shared slice)")
            p.add_argument("--start", nargs="?", const="In Progress", metavar="STATE",
                           help="also transition the issue (default state: 'In Progress')")
        if name == "release":
            p.add_argument("--keep-assignee", action="store_true", help="release the claim but stay assigned")
        if name == "status":
            p.add_argument("--json", action="store_true", help="machine-readable output")
        p.set_defaults(func=fn)

    args = ap.parse_args()
    if not getattr(args, "func", None):
        ap.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
