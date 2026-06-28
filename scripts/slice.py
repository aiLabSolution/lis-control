#!/usr/bin/env python3
"""LIS slice harness — find the next workable slice and coordinate agents, cheaply.

Why this exists
---------------
Agents kept burning ~28k tokens per loop iteration just to answer "what do I work on
next?": the bundled `plane` CLI's `issues list -f json` returns all ~30 fields on every
work item (incl. three description variants + timestamps + UUIDs), the `state` comes back
as a bare UUID that forces a *second* `states` fetch to decode, and the server-side
`--state`/`--assignee` filters are silently ignored by the Plane API — so the agent pulls
the whole backlog and filters it in-context. See `docs/agents/issue-tracker.md`.

This helper does all of that **inside the subprocess** using the Plane REST API's
`?fields=` (trim) and `?expand=state` (inline the name) — so only a tiny, already-filtered,
already-sorted result reaches the agent's context (~1-2k tokens instead of ~28k).

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

Usage
-----
  python3 scripts/slice.py next                 # ready-for-agent ∧ unassigned, stage-ordered
  python3 scripts/slice.py next --stage S2       # only Stage 2 slices
  python3 scripts/slice.py next --json            # machine-readable (id/key/priority/stage)
  python3 scripts/slice.py claim LIS-26 --task "ASTM channel thread" --ttl 120
  python3 scripts/slice.py status LIS-26          # current claim ownership + assignee
  python3 scripts/slice.py heartbeat LIS-26       # extend my claim's TTL
  python3 scripts/slice.py release LIS-26         # drop claim + unassign

Env: PLANE_API_KEY (required); PLANE_WORKSPACE (or PLANE_WORKSPACE_SLUG; default
"labsolution"); PLANE_PROJECT_ID (else .claude/plane-context.json, else the LIS project).
Agent identity: --agent, else LIS_AGENT_ID, else CLAUDE_CODE_SESSION_ID, else host:pid.
Stdlib only.
"""
import os, re, sys, json, socket, argparse
import urllib.request, urllib.error, urllib.parse
from datetime import datetime, timezone, timedelta

WS_DEFAULT = "labsolution"
PROJECT_DEFAULT = "d7f3bcf7-0953-478f-a510-4599e3a2a4bf"  # LIS project
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Triage role realised as a Plane workflow state (docs/agents/triage-labels.md).
READY_STATE = "ready-for-agent"
PRIORITY_RANK = {"urgent": 0, "high": 1, "medium": 2, "low": 3, "none": 4}
# Fields sufficient to *select* work — everything else the dump returns is noise here.
LIST_FIELDS = "id,sequence_id,name,priority,state,parent,assignees"
CLAIM_TAG = "LIS"  # ledger line prefix: "LIS-CLAIM v1 ..."


# --------------------------------------------------------------------------- config
def _workspace() -> str:
    return (os.environ.get("PLANE_WORKSPACE")
            or os.environ.get("PLANE_WORKSPACE_SLUG")
            or WS_DEFAULT)


def _project() -> str:
    if os.environ.get("PLANE_PROJECT_ID"):
        return os.environ["PLANE_PROJECT_ID"]
    ctx = os.path.join(REPO, ".claude", "plane-context.json")
    try:
        with open(ctx, encoding="utf-8") as fh:
            pid = json.load(fh).get("project_id")
            if pid:
                return pid
    except (OSError, ValueError):
        pass
    return PROJECT_DEFAULT


def _agent_id(explicit=None) -> str:
    return (explicit or os.environ.get("LIS_AGENT_ID")
            or os.environ.get("CLAUDE_CODE_SESSION_ID")
            or f"{socket.gethostname()}:{os.getpid()}")


def _key() -> str:
    k = os.environ.get("PLANE_API_KEY")
    if not k:
        sys.exit("PLANE_API_KEY is required (Plane → Profile Settings → Personal Access Tokens).")
    return k


# --------------------------------------------------------------------------- api
def _api(method: str, path: str, params: dict | None = None, body: dict | None = None,
         scoped: bool = True):
    # Most endpoints are workspace-scoped; a few (e.g. /users/me/) are not.
    prefix = f"/workspaces/{_workspace()}" if scoped else ""
    url = f"https://api.plane.so/api/v1{prefix}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"X-API-Key": _key(), "Content-Type": "application/json",
                 "User-Agent": "plane-cli/1.0"},  # default urllib UA is Cloudflare-blocked (1010)
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status == 204:
                return None
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        sys.exit(f"API {method} {path} -> {e.code}: {e.read().decode()[:400]}")
    except urllib.error.URLError as e:
        sys.exit(f"connection error: {e.reason}")


def _paginate(path: str, params: dict) -> list:
    """Follow Plane cursor pagination so we stay correct past 100 items."""
    out, params = [], dict(params)
    params.setdefault("per_page", 100)
    while True:
        page = _api("GET", path, params)
        if isinstance(page, dict) and "results" in page:
            out.extend(page["results"])
            if page.get("next_page_results") and page.get("next_cursor"):
                params["cursor"] = page["next_cursor"]
                continue
        elif isinstance(page, list):
            out.extend(page)
        break
    return out


_ME = {}
def _me() -> str:
    """The token's own user id — used as the coarse 'taken' assignee. Cached."""
    if "id" not in _ME:
        _ME["id"] = _api("GET", "/users/me/", scoped=False)["id"]
    return _ME["id"]


# --------------------------------------------------------------------------- helpers
def _items() -> list:
    """All work items, compact: trimmed fields + state name inlined (one cheap fetch)."""
    proj = _project()
    return _paginate(f"/projects/{proj}/work-items/",
                     {"expand": "state", "fields": LIST_FIELDS})


def _stage(name: str):
    """Stage number from a '[S2.9] ...' title prefix, or None (unstaged)."""
    m = re.match(r"\s*\[S(\d+)(?:\.(\d+))?\]", name or "")
    return (int(m.group(1)), int(m.group(2) or 0)) if m else None


def _by_key(items: list, key: str) -> dict:
    """Find one item by 'LIS-26' / '26' / raw UUID."""
    n = key.upper().removeprefix("LIS-")
    if n.isdigit():
        n = int(n)
        for it in items:
            if it.get("sequence_id") == n:
                return it
    for it in items:
        if it.get("id") == key:
            return it
    sys.exit(f"no work item matching {key!r} in project {_project()}")


def _now():
    return datetime.now(timezone.utc)


def _iso(dt) -> str:
    return dt.replace(microsecond=0).isoformat()


# --------------------------------------------------------------------------- claim ledger
def _post_ledger(issue_id: str, verb: str, agent: str, task: str = "", until=None) -> None:
    line = f"{CLAIM_TAG}-{verb} v1 agent={agent}"
    if task:
        line += f" task={task!r}"
    if until is not None:
        line += f" until={_iso(until)}"
    _api("POST", f"/projects/{_project()}/work-items/{issue_id}/comments/",
         body={"comment_html": f"<p>{line}</p>"})


_LEDGER_RE = re.compile(
    rf"{CLAIM_TAG}-(CLAIM|HEARTBEAT|RELEASE)\s+v1\s+agent=(\S+)"
    r"(?:\s+task=(?:'([^']*)'|\"([^\"]*)\"|(\S+)))?"
    r"(?:\s+until=(\S+))?")


def _read_claims(issue_id: str) -> dict:
    """Reduce the last few ledger comments to current ownership per agent."""
    proj = _project()
    rows = _paginate(f"/projects/{proj}/work-items/{issue_id}/comments/",
                     {"fields": "created_at,actor,comment_stripped", "per_page": 100})
    rows.sort(key=lambda r: r.get("created_at", ""))
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
                active = datetime.fromisoformat(c["until"]) > now
            except ValueError:
                active = True
        c["active"] = active
        live[agent] = c
    return live


# --------------------------------------------------------------------------- commands
def cmd_next(args) -> None:
    items = _items()
    ready = [it for it in items
             if (it.get("state") or {}).get("name") == READY_STATE
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


def cmd_claim(args) -> None:
    items = _items()
    it = _by_key(items, args.key)
    iid, agent = it["id"], _agent_id(args.agent)
    if (it.get("state") or {}).get("name") != READY_STATE:
        print(f"⚠ LIS-{it['sequence_id']} is '{(it.get('state') or {}).get('name')}', "
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
    _api("PATCH", f"/projects/{_project()}/work-items/{iid}/",
         body={"assignees": [_me()]})                      # coarse "taken" flag
    _post_ledger(iid, "CLAIM", agent, args.task, until)     # fine, per-agent record
    print(f"✓ claimed LIS-{it['sequence_id']} as agent={agent} until {_iso(until)}"
          + (f" — task: {args.task}" if args.task else ""))
    if prior:
        print(f"  (shared: also held by {', '.join(prior)} — partition by sub-item.)")


def cmd_heartbeat(args) -> None:
    it = _by_key(_items(), args.key)
    agent = _agent_id(args.agent)
    until = _now() + timedelta(minutes=args.ttl)
    _post_ledger(it["id"], "HEARTBEAT", agent, "", until)
    print(f"✓ heartbeat LIS-{it['sequence_id']} agent={agent} until {_iso(until)}")


def cmd_release(args) -> None:
    it = _by_key(_items(), args.key)
    agent = _agent_id(args.agent)
    _post_ledger(it["id"], "RELEASE", agent)
    if not args.keep_assignee:
        _api("PATCH", f"/projects/{_project()}/work-items/{it['id']}/", body={"assignees": []})
    print(f"✓ released LIS-{it['sequence_id']} (agent={agent}"
          f"{'' if args.keep_assignee else ', unassigned'})")


def cmd_status(args) -> None:
    it = _by_key(_items(), args.key)
    claims = _read_claims(it["id"])
    print(f"LIS-{it['sequence_id']}  {it['name'][:70]}")
    print(f"  state    : {(it.get('state') or {}).get('name')}")
    print(f"  assignee : {'taken' if it.get('assignees') else 'free'}")
    if not claims:
        print("  claims   : none")
        return
    for agent, c in sorted(claims.items(), key=lambda kv: kv[1]["at"]):
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
        if name == "release":
            p.add_argument("--keep-assignee", action="store_true", help="release the claim but stay assigned")
        p.set_defaults(func=fn)

    args = ap.parse_args()
    if not getattr(args, "func", None):
        ap.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
