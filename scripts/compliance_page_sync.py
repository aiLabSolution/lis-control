#!/usr/bin/env python3
"""Regenerate / re-publish a compliance doc as Plane page HTML.

The Plane public API is **create + read only** for pages (no update/delete; see
`docs/agents/compliance-pages.md`). This helper supports the two sync paths from that doc:

  1. --html  : render the doc to a standalone .html file with the same pipeline used to
               publish (tables, neutralized relative links, provenance banner). Open it in a
               browser, select-all, copy, and paste into the existing Plane page's editor —
               same page ID, fast manual update.
  2. --publish : POST a NEW Plane page from the doc and print its URL (the "re-publish" path
               for large rewrites). Then archive the stale page in the Plane UI and update
               the mapping table in docs/agents/compliance-pages.md.

Usage:
  python3 scripts/compliance_page_sync.py threat-model.md            # HTML to stdout
  python3 scripts/compliance_page_sync.py threat-model.md --html     # write <name>.html, print path
  python3 scripts/compliance_page_sync.py threat-model.md --publish  # create a new Plane page

Env for --publish: PLANE_API_KEY (required), PLANE_WORKSPACE (default "labsolution"),
PLANE_PROJECT_ID (default the LIS project).  Dependency: markdown-it-py (stdlib otherwise).
"""
import os, re, sys, json, argparse, urllib.request, urllib.error

WS_DEFAULT = "labsolution"
PROJECT_DEFAULT = "d7f3bcf7-0953-478f-a510-4599e3a2a4bf"  # LIS project
COMPLIANCE_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "compliance")

# file -> published page title (keep in sync with docs/agents/compliance-pages.md)
TITLES = {
    "LIS-10-preparation-brief.md": "LIS-10 · 0 · Preparation Brief (start here)",
    "validation-master-plan-outline.md": "LIS-10 · 1 · Validation Master Plan (VMP) — Outline",
    "npc-registration-checklist.md": "LIS-10 · 2 · NPC Registration & Data-Privacy Checklist",
    "threat-model.md": "LIS-10 · 3 · Threat Model — LabSolution LIS (PHI)",
    "traceability-matrix.md": "LIS-10 · 4 · Traceability Matrix (Seed)",
    "decisions-register.md": "LIS-10 · 5 · Decisions Register (HITL)",
    "reading-list.md": "LIS-10 · 6 · Reading List",
    "responsibility-and-deployment.md": "LIS-10 · 7 · Responsibility & Deployment-Model Compliance",
    "m3-sync-compliance-gate.md": "LIS-10 · 8 · Compliance Extra Work — M3 Sync Gate",
}


def neutralize_relative_links(md_text: str) -> str:
    """[text](relative-or-anchor) -> **text**; keep absolute http(s) links."""
    return re.sub(r"\[([^\]]+)\]\((?!https?://)[^)]*\)", r"**\1**", md_text)


def render_html(fname: str) -> str:
    """Render docs/compliance/<fname> to Plane-ready HTML (same pipeline as publish)."""
    from markdown_it import MarkdownIt  # imported lazily so --help works without the dep
    path = os.path.join(COMPLIANCE_DIR, fname)
    raw = open(path, encoding="utf-8").read()
    banner = (
        f"> 📄 Published mirror of `docs/compliance/{fname}` (repo `aiLabSolution/lis-control`) "
        f"— the **repo is the source of truth**; see issue **LIS-10**.\n\n"
    )
    md = MarkdownIt("commonmark", {"html": True})
    for rule in ("table", "strikethrough"):
        md.enable(rule)
    return md.render(banner + neutralize_relative_links(raw))


def publish(fname: str, html: str) -> None:
    key = os.environ.get("PLANE_API_KEY")
    if not key:
        sys.exit("PLANE_API_KEY is required for --publish")
    ws = os.environ.get("PLANE_WORKSPACE", WS_DEFAULT)
    project = os.environ.get("PLANE_PROJECT_ID", PROJECT_DEFAULT)
    title = TITLES.get(fname, fname)
    url = f"https://api.plane.so/api/v1/workspaces/{ws}/projects/{project}/pages/"
    body = json.dumps({"name": title, "description_html": html, "access": 0}).encode()
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"X-API-Key": key, "Content-Type": "application/json",
                 "User-Agent": "plane-cli/1.0"},  # default urllib UA is Cloudflare-blocked (1010)
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            page = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        sys.exit(f"create failed {e.code}: {e.read().decode()[:300]}")
    pid = page.get("id")
    print(f"created page {pid}")
    print(f"https://app.plane.so/{ws}/projects/{project}/pages/{pid}/")
    print("NOTE: archive the stale page in the Plane UI and update the ID in "
          "docs/agents/compliance-pages.md")


def main() -> None:
    ap = argparse.ArgumentParser(description="Render/re-publish a compliance doc as a Plane page.")
    ap.add_argument("file", help="filename under docs/compliance/, e.g. threat-model.md")
    ap.add_argument("--html", action="store_true", help="write rendered HTML to a file and print its path")
    ap.add_argument("--publish", action="store_true", help="create a NEW Plane page via the API")
    ap.add_argument("--out", help="output path for --html (default: alongside scratch)")
    args = ap.parse_args()

    fname = os.path.basename(args.file)
    if not os.path.exists(os.path.join(COMPLIANCE_DIR, fname)):
        sys.exit(f"no such doc: docs/compliance/{fname}")

    html = render_html(fname)
    if args.publish:
        publish(fname, html)
    elif args.html:
        out = args.out or os.path.join(os.path.dirname(__file__), fname.replace(".md", ".html"))
        page = (f"<!doctype html><meta charset=utf-8>"
                f"<title>{TITLES.get(fname, fname)}</title>"
                f"<body style='max-width:820px;margin:2rem auto;font:16px/1.5 system-ui'>{html}</body>")
        open(out, "w", encoding="utf-8").write(page)
        print(out)
        print("Open in a browser, select-all, copy, and paste into the Plane page editor.")
    else:
        sys.stdout.write(html)


if __name__ == "__main__":
    main()
