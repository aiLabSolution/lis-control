#!/usr/bin/env python3
"""Render the Stage 1 & 2 slice decision dossier to PDF.

Markdown -> styled HTML -> PDF via headless Chromium (same toolchain + house
style as scripts/build_signoff_pdfs.py). Reproducible: paths derive from this
file's location; the PDF lands next to its source md in docs/decisions/.
Requires `markdown-it-py` and `chromium` on PATH.

    python3 scripts/build_decision_pdf.py
"""
import os, subprocess
from markdown_it import MarkdownIt

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEC  = os.path.join(REPO, "docs/decisions")
SRC  = os.path.join(DEC, "stage-1-2-slice-decision-dossier.md")
OUT  = os.path.join(DEC, "stage-1-2-slice-decision-dossier.pdf")

md = MarkdownIt("commonmark", {"html": True, "linkify": True})
for rule in ("table", "strikethrough"):
    try: md.enable(rule)
    except Exception: pass

# House style — kept in sync with scripts/build_signoff_pdfs.py.
CSS = """
@page { size: A4; margin: 16mm 14mm 16mm 14mm; }
* { box-sizing: border-box; }
body { font-family: "Inter","Helvetica Neue",Arial,"Noto Sans","Noto Color Emoji",sans-serif;
       font-size: 10.5px; line-height: 1.5; color: #1a2230; margin: 0; }
.doc { page-break-before: always; }
.doc:first-of-type { page-break-before: avoid; }
h1 { font-size: 21px; color: #0f2747; border-bottom: 3px solid #2563eb; padding-bottom: 6px; margin: 0 0 14px; }
h2 { font-size: 15px; color: #14306a; border-bottom: 1px solid #d6deea; padding-bottom: 3px; margin: 22px 0 8px; }
h3 { font-size: 12.5px; color: #1f3b73; margin: 16px 0 6px; }
h4 { font-size: 11px; color: #33415c; margin: 12px 0 4px; }
p, li { margin: 5px 0; }
a { color: #1d4ed8; text-decoration: none; }
code { font-family: "JetBrains Mono","SFMono-Regular",Consolas,monospace; font-size: 9px;
       background: #eef2f8; padding: 1px 4px; border-radius: 3px; color: #b3204a; }
pre { background: #0f1b2d; color: #e6edf6; padding: 10px; border-radius: 6px; overflow-x: auto; }
pre code { background: none; color: inherit; padding: 0; }
blockquote { margin: 10px 0; padding: 8px 12px; background: #f4f7fc; border-left: 4px solid #2563eb;
             border-radius: 0 5px 5px 0; }
blockquote p { margin: 3px 0; }
table { border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 8.2px; table-layout: auto; }
th, td { border: 1px solid #c9d4e3; padding: 4px 6px; text-align: left; vertical-align: top;
         word-break: break-word; overflow-wrap: anywhere; }
th { background: #1f3b73; color: #fff; font-weight: 600; }
tr:nth-child(even) td { background: #f5f8fc; }
hr { border: none; border-top: 1px solid #d6deea; margin: 18px 0; }
strong { color: #0f2747; }
.cover { page-break-after: always; text-align: center; padding-top: 60mm; }
.cover .badge { display:inline-block; background:#fef3c7; color:#92400e; border:1px solid #f59e0b;
                border-radius: 999px; padding: 4px 14px; font-size: 11px; font-weight:600; letter-spacing:.3px; }
.cover h1 { border: none; font-size: 28px; color:#0f2747; margin: 22px 40px 6px; }
.cover .sub { font-size: 14px; color:#33415c; margin: 0 40px; }
.cover .meta { margin-top: 28px; font-size: 11px; color:#475569; }
.cover .toc { margin: 24px auto 0; width: 80%; text-align:left; font-size: 10px; color:#1f3b73; }
.cover .toc li { margin: 3px 0; }
"""

with open(SRC, encoding="utf-8") as f:
    body = md.render(f.read())

toc = "".join(f"<li>{t}</li>" for t in [
    "0 — Read first: the SD-0 scope ruling (ADR-0008 ↔ LIS-74)",
    "1 — Decision summary table (SD-0 … SD-9)",
    "2 — Stage-1 decisions (SD-1/3/6/8/9a)",
    "3 — Stage-2 decisions (SD-2/4/5/7/9b)",
    "4 — Suggested decision order",
    "5 — Context: non-decision Stage 1–2 slices",
    "6 — Decisions taken (2026-06-29) — outcomes + Plane states applied",
])
cover = f"""<div class="cover">
  <span class="badge" style="background:#dcfce7;color:#166534;border-color:#22c55e;">DECISIONS RULED · 2026-06-29</span>
  <h1>LabSolution LIS — Stage 1 &amp; 2 Slice Decision Dossier</h1>
  <div class="sub">Human-in-the-loop decision package — ruled by M. Uy (system/technical owner); see §6</div>
  <div class="meta">Ruled 2026-06-29 · the original review draft landed via PR #25 · this record supersedes it<br>
  Source of truth: <code>docs/decisions/stage-1-2-slice-decision-dossier.md</code><br>
  Owners: M. Uy (system/technical) · A. L. Pinote (QA/regulatory) — ADR-0007</div>
  <ol class="toc">{toc}</ol>
</div>"""

doc = (f'<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head>'
       f'<body>{cover}<div class="doc">{body}</div></body></html>')
htmlpath = OUT.replace(".pdf", ".html")
with open(htmlpath, "w", encoding="utf-8") as f:
    f.write(doc)
subprocess.run(["chromium", "--headless", "--no-sandbox", "--disable-gpu",
    "--no-pdf-header-footer", "--virtual-time-budget=12000",
    f"--print-to-pdf={OUT}", f"file://{htmlpath}"],
    check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
os.remove(htmlpath)
print(f"  - {os.path.basename(OUT)}  ({os.path.getsize(OUT)//1024} KB)")
