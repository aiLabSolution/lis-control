#!/usr/bin/env python3
"""Shared Plane.so REST plumbing for the repo's agent tooling. Stdlib only.

`scripts/slice.py` (find/read/claim/coordinate) and `scripts/plane_issue.py`
(create/update/comment with rendered markdown) talk to the Plane API the same
way: workspace/project resolution from env + `.claude/plane-context.json`, an
authenticated request with the Cloudflare-safe User-Agent, cursor pagination,
LIS-NN -> UUID resolution backed by a per-checkout cache, and state-name ->
UUID resolution. This module is that shared layer — no CLI entry point here.

Env: PLANE_API_KEY (required); PLANE_WORKSPACE (or PLANE_WORKSPACE_SLUG;
default "labsolution"); PLANE_PROJECT_ID (else .claude/plane-context.json,
else the LIS project).
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

WS_DEFAULT = "labsolution"
PROJECT_DEFAULT = "d7f3bcf7-0953-478f-a510-4599e3a2a4bf"  # LIS project
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# LIS-NN -> UUID lookaside (sequence_id assignments are immutable, so entries
# never invalidate; a deleted item 404s and falls back to a fresh scan).
CACHE = os.path.join(REPO, ".claude", "slice-cache.json")
# Fields sufficient to *select* work — everything else the dump returns is noise here.
LIST_FIELDS = "id,sequence_id,name,priority,state,parent,assignees"
_UUID_RE = re.compile(r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.IGNORECASE)


# --------------------------------------------------------------------------- config
def workspace() -> str:
    return (os.environ.get("PLANE_WORKSPACE")
            or os.environ.get("PLANE_WORKSPACE_SLUG")
            or WS_DEFAULT)


def project() -> str:
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


def api_key() -> str:
    k = os.environ.get("PLANE_API_KEY")
    if not k:
        sys.exit("PLANE_API_KEY is required (Plane → Profile Settings → Personal Access Tokens).")
    return k


# --------------------------------------------------------------------------- api
def api(method: str, path: str, params: dict | None = None, body: dict | None = None,
        scoped: bool = True, ok404: bool = False):
    """One authenticated request. Most endpoints are workspace-scoped; a few
    (e.g. /users/me/) are not. `ok404` returns None instead of exiting, so a
    stale cache entry can self-heal instead of killing the command."""
    prefix = f"/workspaces/{workspace()}" if scoped else ""
    url = f"https://api.plane.so/api/v1{prefix}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    for attempt in (1, 2):
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={"X-API-Key": api_key(), "Content-Type": "application/json",
                     "User-Agent": "plane-cli/1.0"},  # default urllib UA is Cloudflare-blocked (1010)
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status == 204:
                    return None
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 404 and ok404:
                return None
            sys.exit(f"API {method} {path} -> {e.code}: {e.read().decode()[:400]}")
        except OSError as e:
            # Covers URLError plus raw mid-response resets (ConnectionResetError
            # leaks past URLError). Retry once, but only for idempotent reads —
            # a replayed POST could double-write.
            reason = getattr(e, "reason", e)
            if method == "GET" and attempt == 1:
                time.sleep(1)
                continue
            sys.exit(f"connection error on {method} {path}: {reason}")


def paginate(path: str, params: dict | None = None) -> list:
    """Follow Plane cursor pagination so results stay correct past 100 items."""
    out, params = [], dict(params or {})
    params.setdefault("per_page", 100)
    while True:
        page = api("GET", path, params)
        if isinstance(page, dict) and "results" in page:
            out.extend(page["results"])
            if page.get("next_page_results") and page.get("next_cursor"):
                params["cursor"] = page["next_cursor"]
                continue
        elif isinstance(page, list):
            out.extend(page)
        break
    return out


_ME: dict = {}


def me() -> str:
    """The token's own user id — the coarse 'taken' assignee. Cached per process."""
    if "id" not in _ME:
        _ME["id"] = api("GET", "/users/me/", scoped=False)["id"]
    return _ME["id"]


def items() -> list:
    """All work items, compact: trimmed fields + state name inlined (one cheap fetch)."""
    return paginate(f"/projects/{project()}/work-items/",
                    {"expand": "state", "fields": LIST_FIELDS})


# --------------------------------------------------------------------------- resolution
def _cache_load() -> dict:
    try:
        with open(CACHE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _cache_store(mapping: dict) -> None:
    cache = _cache_load()
    cache.update(mapping)
    try:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        with open(CACHE, "w", encoding="utf-8") as fh:
            json.dump(cache, fh)
    except OSError:
        pass  # the cache is an optimisation; never fail the command over it


def resolve_item(key: str, fresh: list | None = None):
    """'LIS-26' / '26' / raw UUID -> compact work item (LIST_FIELDS + state name).

    Hits go through the per-checkout cache + one single-item GET instead of a
    full-backlog scan (heartbeat/status run every loop iteration — the scan is
    the exact token/latency cost this file exists to avoid). A miss or a stale
    entry falls back to one scan and refreshes the cache for every later call.
    """
    n = key.upper().removeprefix("LIS-")
    if _UUID_RE.fullmatch(key):
        iid = key
    elif n.isdigit():
        iid = _cache_load().get(n)
    else:
        iid = None
    if iid:
        it = api("GET", f"/projects/{project()}/work-items/{iid}/",
                 {"expand": "state", "fields": LIST_FIELDS}, ok404=True)
        if it:
            return it
    all_items = fresh if fresh is not None else items()
    _cache_store({str(i["sequence_id"]): i["id"] for i in all_items if i.get("sequence_id")})
    if n.isdigit():
        for it in all_items:
            if it.get("sequence_id") == int(n):
                return it
    for it in all_items:
        if it.get("id") == key:
            return it
    sys.exit(f"no work item matching {key!r} in project {project()}")


def state_id(ref: str) -> str:
    """Accept a state UUID or *name* ('ready-for-agent', 'In Progress', ...)."""
    if _UUID_RE.fullmatch(ref):
        return ref
    states = paginate(f"/projects/{project()}/states/")
    for s in states:
        if s.get("name") == ref:
            return s["id"]
    lowered = {s.get("name", "").lower(): s["id"] for s in states}
    if ref.lower() in lowered:
        return lowered[ref.lower()]
    sys.exit(f"no state named {ref!r}; project states: "
             + ", ".join(sorted(s.get("name", "?") for s in states)))


def state_name(item: dict) -> str:
    """State name whether the item came back expanded (dict) or bare (UUID str)."""
    st = item.get("state")
    return st.get("name", "?") if isinstance(st, dict) else (st or "?")
