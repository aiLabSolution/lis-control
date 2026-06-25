#!/usr/bin/env python3
"""Render the LIS-10 compliance sign-off + review dossier to PDF.

Markdown -> styled HTML -> PDF via headless Chromium. Reproducible: paths are
derived from this file's location, output lands in docs/compliance/sign-off/pdf/
(gitignored). Requires `markdown-it-py` and `chromium` on PATH.

    python3 scripts/build_signoff_pdfs.py
"""
import os, subprocess, html as htmlmod
from markdown_it import MarkdownIt

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMP = os.path.join(REPO, "docs/compliance")
SIGN = os.path.join(COMP, "sign-off")
ADR  = os.path.join(REPO, "docs/adr")
OUT  = os.path.join(SIGN, "pdf")
os.makedirs(OUT, exist_ok=True)

md = MarkdownIt("commonmark", {"html": True, "linkify": True})
for rule in ("table", "strikethrough"):
    try: md.enable(rule)
    except Exception: pass

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
.cover { page-break-after: always; text-align: center; padding-top: 70mm; }
.cover .badge { display:inline-block; background:#fef3c7; color:#92400e; border:1px solid #f59e0b;
                border-radius: 999px; padding: 4px 14px; font-size: 11px; font-weight:600; letter-spacing:.3px; }
.cover h1 { border: none; font-size: 30px; color:#0f2747; margin: 22px 40px 6px; }
.cover .sub { font-size: 14px; color:#33415c; margin: 0 40px; }
.cover .meta { margin-top: 30px; font-size: 11px; color:#475569; }
.cover .toc { margin: 26px auto 0; width: 76%; text-align:left; font-size: 10px; color:#1f3b73; }
.cover .toc li { margin: 3px 0; }
"""

def render_md(path):
    with open(path, encoding="utf-8") as f:
        return md.render(f.read())

def page(body_html, outfile):
    doc = f'<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head><body>{body_html}</body></html>'
    htmlpath = os.path.join(OUT, outfile.replace(".pdf", ".html"))
    with open(htmlpath, "w", encoding="utf-8") as f:
        f.write(doc)
    pdfpath = os.path.join(OUT, outfile)
    subprocess.run(["chromium","--headless","--no-sandbox","--disable-gpu",
        "--no-pdf-header-footer","--virtual-time-budget=12000",
        f"--print-to-pdf={pdfpath}", f"file://{htmlpath}"],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.remove(htmlpath)
    print(f"  - {outfile}  ({os.path.getsize(pdfpath)//1024} KB)")

# standalone sign-off docs
page(f'<div class="doc">{render_md(f"{SIGN}/LIS-10-review-and-acceptance-record.md")}</div>',
     "LIS-10-review-and-acceptance-record.pdf")
page(f'<div class="doc">{render_md(f"{SIGN}/LIS-10-dpo-designation-and-independence-charter.md")}</div>',
     "LIS-10-dpo-designation-and-independence-charter.pdf")

# combined review dossier (cover + all relevant docs)
DOSSIER = [
    f"{SIGN}/LIS-10-review-and-acceptance-record.md",
    f"{SIGN}/LIS-10-dpo-designation-and-independence-charter.md",
    f"{COMP}/LIS-10-preparation-brief.md",
    f"{COMP}/validation-master-plan-outline.md",
    f"{COMP}/npc-registration-checklist.md",
    f"{COMP}/threat-model.md",
    f"{COMP}/traceability-matrix.md",
    f"{COMP}/decisions-register.md",
    f"{COMP}/responsibility-and-deployment.md",
    f"{COMP}/m3-sync-compliance-gate.md",
    f"{ADR}/0004-deployment-topology.md",
    f"{ADR}/0005-regulatory-ownership-and-responsibility-allocation.md",
    f"{ADR}/0006-interface-engine-stack-and-fleet-scope.md",
]
titles = ["Sign-off — Review & Acceptance Record","Sign-off — DPO Designation & Independence Charter",
    "Preparation brief (start here)","Core 1 — Validation Master Plan (outline)",
    "Core 2 — NPC registration checklist","Core 3 — Threat model (STRIDE)",
    "Core 4 — Traceability matrix (seed)","Decisions register (HITL)",
    "Responsibility & deployment (PIC/PIP)","M3 sync compliance gate",
    "ADR-0004 — Deployment topology","ADR-0005 — Regulatory ownership",
    "ADR-0006 — Interface engine / stack / fleet"]
toc = "".join(f"<li>{i+1}. {htmlmod.escape(t)}</li>" for i,t in enumerate(titles))
cover = f"""<div class="cover">
  <span class="badge">FOR REVIEW · PENDING SIGNATURES</span>
  <h1>LabSolution LIS — LIS-10 Review Dossier</h1>
  <div class="sub">Stage-0 Compliance Scaffold (S0.8) — review package for slice close-out</div>
  <div class="meta">Branch <code>lis-10-compliance-scaffold</code> · PR #3<br>
  Source of truth: <code>docs/compliance/</code> · Not legal advice — counsel confirmation per the acceptance record §4</div>
  <ol class="toc">{toc}</ol>
</div>"""
page(cover + "".join(f'<div class="doc">{render_md(p)}</div>' for p in DOSSIER),
     "LIS-10-review-dossier.pdf")
print(f"PDFs written to {OUT}")
