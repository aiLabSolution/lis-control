#!/usr/bin/env python3
"""Create Plane work items with the body in the **description**, not a comment.

Why this exists
---------------
Plane work items have a rich-text *description*. The bundled `plane` CLI's
`issues create --description` wraps whatever you pass in a single
`<p>{escaped}</p>` (and a single shell arg is awkward for a multi-line markdown
PRD), so the repo convention used to route bodies into the *first comment*
instead — leaving every issue with an empty description (see
`docs/agents/issue-tracker.md`). That's backwards: the body is the description.

This helper renders a markdown body into clean `description_html` and POSTs it on
creation, so the issue reads correctly in Plane and comments stay reserved for the
progress log + claim ledger. It wraps the Plane REST API directly (stdlib only),
the same way `scripts/slice.py` does, rather than depending on the global CLI.

Usage
-----
  python3 scripts/plane_issue.py create --name "[S2.4] ERBA EC90 channel thread" \
      --body-file slice.md [--priority high] [--parent UUID] [--label UUID]
  printf '%s' "$BODY" | python3 scripts/plane_issue.py create --name "…" --body-file -
  python3 scripts/plane_issue.py render --body-file slice.md     # preview HTML, no network
  python3 scripts/plane_issue.py create --name "…" --body-file b.md --dry-run

Env: PLANE_API_KEY (required); PLANE_WORKSPACE (or PLANE_WORKSPACE_SLUG; default
"labsolution"); PLANE_PROJECT_ID (else .claude/plane-context.json, else the LIS
project). Stdlib only.

Markdown coverage (deliberately small — matches the PRD/slice body template):
ATX headings (#..######), unordered (-,*,+) and ordered (1.) lists, task items
([ ] / [x]), fenced ``` code blocks, blockquotes, --- rules, blank-line
paragraphs (single newlines preserved as <br>), inline **bold**, `code`, and
[text](url) links (http/https/mailto/relative only). Anything else passes through
as literal text — never as raw HTML.
"""
import os, re, sys, json, argparse
import urllib.request, urllib.error, urllib.parse

WS_DEFAULT = "labsolution"
PROJECT_DEFAULT = "d7f3bcf7-0953-478f-a510-4599e3a2a4bf"  # LIS project
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRIORITY = {"urgent": 1, "high": 2, "medium": 3, "low": 4, "none": 0}


# --------------------------------------------------------------------------- markdown
def _esc(s: str) -> str:
    """Escape HTML metacharacters for text AND double-quoted-attribute contexts.
    Quotes are escaped too so author text can never break out of an attribute
    (e.g. a fenced-code ```lang string that lands in class="..."). Never raw markup."""
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))


def _link(m: "re.Match") -> str:
    text, url = m.group(1), m.group(2)  # both already _esc()'d by the caller
    # Reject protocol-relative (//host) and any non-allowlisted scheme — render the
    # literal markdown instead of an <a> (no javascript:/data:/off-site smuggling).
    if url.startswith("//") or not re.match(r"(?:https?:|mailto:|/|#|\.)", url, re.IGNORECASE):
        return m.group(0)
    return f'<a href="{url}">{text}</a>'


def _inline(text: str) -> str:
    """Render inline markdown on a single segment. Escapes first, so input is plain text."""
    text = text.replace("\x00", "")  # NUL is our link sentinel; never allow it from input
    out = []
    # Split out `code` spans so their contents are never treated as bold/link markup.
    for part in re.split(r"(`[^`]+`)", text):
        if len(part) >= 2 and part.startswith("`") and part.endswith("`"):
            out.append(f"<code>{_esc(part[1:-1])}</code>")
            continue
        seg = _esc(part)
        # Stash rendered links behind sentinels BEFORE the bold pass, so `**` inside a
        # URL can't be rewritten into the href. Link text excludes brackets to bound
        # backtracking on pathological input (e.g. a long run of '[').
        links: list = []

        def _stash(m: "re.Match") -> str:
            links.append(_link(m))
            return f"\x00{len(links) - 1}\x00"

        seg = re.sub(r"\[([^\][]+)\]\(([^)\s[]+)\)", _stash, seg)      # [text](url)
        seg = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", seg)  # **bold**
        seg = re.sub(r"\x00(\d+)\x00", lambda mm: links[int(mm.group(1))], seg)
        out.append(seg)
    return "".join(out)


_LIST_RE = re.compile(r"^(\s*)([-*+]|\d+\.)\s+(.*)$")
_HR_RE = re.compile(r"^(---+|\*\*\*+|___+)$")
_HEAD_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def _is_block_start(line: str) -> bool:
    s = line.strip()
    return bool(
        s.startswith("```") or s.startswith(">")
        or _HEAD_RE.match(line) or _LIST_RE.match(line) or _HR_RE.match(s)
    )


def md_to_html(md: str) -> str:
    """Render a markdown body to Plane-friendly description_html. Stdlib only."""
    lines = md.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list = []
    i = 0
    while i < len(lines):
        line = lines[i]
        s = line.strip()

        if s.startswith("```"):                                  # fenced code
            lang = s[3:].strip()
            i += 1
            buf = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i]); i += 1
            i += 1  # consume the closing fence (or fall off the end)
            cls = f' class="language-{_esc(lang)}"' if lang else ""
            out.append(f"<pre><code{cls}>{_esc(chr(10).join(buf))}</code></pre>")
            continue

        if not s:                                                # blank line
            i += 1; continue

        m = _HEAD_RE.match(line)                                 # heading
        if m:
            lvl = len(m.group(1))
            out.append(f"<h{lvl}>{_inline(m.group(2).strip())}</h{lvl}>")
            i += 1; continue

        if _HR_RE.match(s):                                      # horizontal rule
            out.append("<hr>"); i += 1; continue

        if s.startswith(">"):                                    # blockquote
            buf = []
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                buf.append(re.sub(r"^\s*>\s?", "", lines[i])); i += 1
            out.append(f"<blockquote>{'<br>'.join(_inline(b) for b in buf)}</blockquote>")
            continue

        m = _LIST_RE.match(line)                                 # list (ul / ol)
        if m:
            ordered = bool(re.match(r"\d+\.", m.group(2)))
            tag = "ol" if ordered else "ul"
            items = []
            while i < len(lines):
                lm = _LIST_RE.match(lines[i])
                if not lm or bool(re.match(r"\d+\.", lm.group(2))) != ordered:
                    break
                content = lm.group(3)
                tm = re.match(r"\[([ xX])\]\s+(.*)$", content)   # task item
                if tm:
                    box = "☑ " if tm.group(1).lower() == "x" else "☐ "
                    items.append(f"<li>{box}{_inline(tm.group(2))}</li>")
                else:
                    items.append(f"<li>{_inline(content)}</li>")
                i += 1
            out.append(f"<{tag}>{''.join(items)}</{tag}>")
            continue

        buf = []                                                 # paragraph
        while i < len(lines) and lines[i].strip() and not _is_block_start(lines[i]):
            buf.append(lines[i]); i += 1
        out.append(f"<p>{'<br>'.join(_inline(b) for b in buf)}</p>")

    return "\n".join(out)


# --------------------------------------------------------------------------- config / api
def _workspace() -> str:
    return (os.environ.get("PLANE_WORKSPACE")
            or os.environ.get("PLANE_WORKSPACE_SLUG") or WS_DEFAULT)


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


def _key() -> str:
    k = os.environ.get("PLANE_API_KEY")
    if not k:
        sys.exit("PLANE_API_KEY is required (Plane → Profile Settings → Personal Access Tokens).")
    return k


def _api(method: str, path: str, body: dict | None = None):
    url = f"https://api.plane.so/api/v1/workspaces/{_workspace()}{path}"
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


def _read_body(path: str | None) -> str:
    """Read the markdown body from a file, or stdin when path is '-' / omitted-with-pipe."""
    if path and path != "-":
        try:
            with open(path, encoding="utf-8") as fh:
                return fh.read()
        except OSError as e:
            sys.exit(f"cannot read body file {path!r}: {e}")
    if path == "-" or not sys.stdin.isatty():
        return sys.stdin.read()
    sys.exit("no body: pass --body-file PATH, --body-file - , or pipe the body on stdin.")


def build_payload(name: str, body_md: str, priority: str | None = None,
                  parent: str | None = None, label: str | None = None,
                  state: str | None = None) -> dict:
    """Assemble the work-item create payload (pure; no network — unit-testable)."""
    payload: dict = {"name": name}
    body_md = (body_md or "").strip()
    if body_md:
        payload["description_html"] = md_to_html(body_md)
    if priority:
        payload["priority"] = PRIORITY.get(priority.lower(), 3)
    if parent:
        payload["parent"] = parent
    if label:
        payload["labels"] = [label]
    if state:
        payload["state"] = state
    return payload


# --------------------------------------------------------------------------- commands
def cmd_create(args) -> None:
    payload = build_payload(args.name, _read_body(args.body_file),
                            args.priority, args.parent, args.label, args.state)
    if args.dry_run:
        print(json.dumps(payload, indent=2))
        return
    data = _api("POST", f"/projects/{_project()}/work-items/", body=payload)
    seq, iid = data.get("sequence_id"), data.get("id")
    print(f"✓ created LIS-{seq} ({iid})")
    if args.json:
        print(json.dumps(data, indent=2))


def cmd_render(args) -> None:
    print(md_to_html(_read_body(args.body_file)))


def main() -> None:
    ap = argparse.ArgumentParser(prog="plane_issue", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd")

    c = sub.add_parser("create", help="create a work item with a rendered description")
    c.add_argument("--name", required=True, help="work item title")
    c.add_argument("--body-file", help="markdown body file, or '-' for stdin (else piped stdin)")
    c.add_argument("--priority", choices=list(PRIORITY), help="priority level")
    c.add_argument("--parent", help="parent work item UUID (creates a sub-item)")
    c.add_argument("--label", help="label UUID")
    c.add_argument("--state", help="state UUID")
    c.add_argument("--dry-run", action="store_true", help="print the payload; do not POST")
    c.add_argument("--json", action="store_true", help="also print the created item JSON")
    c.set_defaults(func=cmd_create)

    r = sub.add_parser("render", help="render a body to description_html (no network)")
    r.add_argument("--body-file", help="markdown body file, or '-' for stdin (else piped stdin)")
    r.set_defaults(func=cmd_render)

    args = ap.parse_args()
    if not getattr(args, "func", None):
        ap.print_help(); sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
