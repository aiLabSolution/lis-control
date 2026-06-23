# Compliance docs ↔ Plane pages (mirror + sync)

The compliance scaffold under [`docs/compliance/`](../compliance/) is **mirrored to Plane
project pages** in the **LIS** project, so the documents are readable/collaborable inside
Plane alongside the work items.

> **The repo is the source of truth.** The Plane pages are a published mirror. When a
> `docs/compliance/*.md` file changes, **update the matching Plane page** (see the procedure
> below). Never treat the Plane page as canonical — reconcile it back to the repo if they
> diverge.

## File → Plane page mapping

Workspace `labsolution` · project `LIS` (`d7f3bcf7-0953-478f-a510-4599e3a2a4bf`). Page URL
pattern: `https://app.plane.so/labsolution/projects/d7f3bcf7-0953-478f-a510-4599e3a2a4bf/pages/<page_id>/`.

| Source file (`docs/compliance/`) | Plane page title | Page ID |
|---|---|---|
| `LIS-10-preparation-brief.md` | LIS-10 · 0 · Preparation Brief (start here) | `0e893ee7-8f59-4a65-9b43-bafc45d691a6` |
| `validation-master-plan-outline.md` | LIS-10 · 1 · Validation Master Plan (VMP) — Outline | `52ad04c3-4670-494f-9758-e76d380339d9` |
| `npc-registration-checklist.md` | LIS-10 · 2 · NPC Registration & Data-Privacy Checklist | `884553de-a9e4-42d1-9514-add4f2217777` |
| `threat-model.md` | LIS-10 · 3 · Threat Model — LabSolution LIS (PHI) | `cf06758f-5655-4ff1-b07f-4b64349e9cee` |
| `traceability-matrix.md` | LIS-10 · 4 · Traceability Matrix (Seed) | `1da52f8b-12a5-48bc-8f78-461ef2064a74` |
| `decisions-register.md` | LIS-10 · 5 · Decisions Register (HITL) | `e5f4915c-01c0-4655-84a6-96b6821b3a3b` |
| `reading-list.md` | LIS-10 · 6 · Reading List | `68c5677e-c36a-4e0a-82ad-d0de8056e225` |

`README.md` is the repo folder index and is intentionally **not** mirrored. New compliance
docs added later should be published as a new page and added to this table.

## ⚠️ Plane public-API limitation (verified 2026-06-23)

The Plane **public REST API** (`X-API-Key`, `https://api.plane.so/api/v1`) supports **only
`create` and `read` for pages** — `PATCH`/`PUT`/`DELETE` return **405**, `/archive/` returns
**404**, and `parent_id` is **silently ignored** (pages are flat; titles are prefixed
`LIS-10 · N ·` to group them). So an agent **cannot update or delete an existing page**
through the API.

## Sync procedure — when a `docs/compliance/*.md` changes

1. **Repo first.** Commit the change in `docs/compliance/` (source of truth).
2. **Update the matching page.** Because the API cannot update a page, do **one** of —
   the helper `scripts/compliance_page_sync.py` automates both:
   - **Preferred — edit in the Plane UI:** run
     `python3 scripts/compliance_page_sync.py <file> --html` → open the printed `.html` in a
     browser, select-all, copy, and paste into the existing page's editor. Keeps the same
     page ID/links. Manual but exact.
   - **Re-publish via API:** run `python3 scripts/compliance_page_sync.py <file> --publish`
     (creates a NEW page, prints its URL), then **archive the stale page in the Plane UI**
     and update its ID in the table above. Use this only for large rewrites.
3. **Keep this table accurate** — if a page ID changes (re-publish) or a doc is added/removed,
   update the mapping here in the same commit.

### How a page was published (for re-publish / new docs)

```
POST https://api.plane.so/api/v1/workspaces/labsolution/projects/<project_id>/pages/
headers: X-API-Key: $PLANE_API_KEY · Content-Type: application/json · User-Agent: plane-cli/1.0
body:    {"name": "<title>", "description_html": "<html>", "access": 0}
```

- `description_html` is **required**. Convert the markdown to HTML with `markdown-it-py`
  (`MarkdownIt("commonmark", {"html": True})` with the `table` and `strikethrough` rules
  enabled); neutralize relative/anchor links (`[t](x.md)` → `**t**`) since cross-page
  relative links don't resolve in Plane.
- **Set `User-Agent: plane-cli/1.0`** (the bundled `plane` CLI's UA). The default
  `python-urllib` UA is blocked by Cloudflare with error **1010**.
- The `plane` CLI (`docs/agents/issue-tracker.md`) has **no `pages` command** — pages are
  driven by direct API calls only.
