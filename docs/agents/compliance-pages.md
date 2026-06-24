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
| `LIS-10-preparation-brief.md` | LIS-10 · 0 · Preparation Brief (start here) | `f66624a7-f13e-4e21-995d-b84dbd695c43` |
| `validation-master-plan-outline.md` | LIS-10 · 1 · Validation Master Plan (VMP) — Outline | `7115203a-67ac-4880-b4be-32884c67d8af` |
| `npc-registration-checklist.md` | LIS-10 · 2 · NPC Registration & Data-Privacy Checklist | `da596d0b-106f-4c1d-ac3c-36fa8ec14fc6` |
| `threat-model.md` | LIS-10 · 3 · Threat Model — LabSolution LIS (PHI) | `4e4ae30b-f8c4-42ce-ac59-139158e2e025` |
| `traceability-matrix.md` | LIS-10 · 4 · Traceability Matrix (Seed) | `fc193d2d-cab2-4a92-bef7-c4ee57a18a30` |
| `decisions-register.md` | LIS-10 · 5 · Decisions Register (HITL) | `4117ee8a-331d-45b6-b293-b4c1dce7750d` |
| `reading-list.md` | LIS-10 · 6 · Reading List | `16e3406d-c241-4d79-a0ba-30467ee09cb5` |
| `responsibility-and-deployment.md` | LIS-10 · 7 · Responsibility & Deployment-Model Compliance | `e3169782-0530-4fea-9625-e24f99d3a19a` |
| `m3-sync-compliance-gate.md` | LIS-10 · 8 · Compliance Extra Work — M3 Sync Gate | `d3d78f8e-48ff-4600-a285-7b455bc12791` |

`README.md` is the repo folder index and is intentionally **not** mirrored. ADRs (e.g.
`docs/adr/0002-deployment-topology.md`) live outside `docs/compliance/` and are **not** mirrored
here. New compliance docs added later should be published as a new page and added to this table.

> **⚠️ Sync status (2026-06-24 — topology decision).** The deployment-topology decision
> ([ADR-0002](../adr/0002-deployment-topology.md)) revised **every** mirrored compliance doc and
> added two new docs.
> - ✅ **Rows 7–8 published** (new pages — IDs recorded above).
> - ✅ **Pages 0–6 re-published** via API (the public API can't update a page in place); the
>   **new** page IDs are recorded in the table above.
> - 🗑️ **ACTION — archive the 7 stale pages in the Plane UI** (the API can't archive/delete
>   pages). Their **old** IDs:
>   `0e893ee7-8f59-4a65-9b43-bafc45d691a6` (0 · brief),
>   `52ad04c3-4670-494f-9758-e76d380339d9` (1 · VMP),
>   `884553de-a9e4-42d1-9514-add4f2217777` (2 · NPC),
>   `cf06758f-5655-4ff1-b07f-4b64349e9cee` (3 · threat model),
>   `1da52f8b-12a5-48bc-8f78-461ef2064a74` (4 · matrix),
>   `e5f4915c-01c0-4655-84a6-96b6821b3a3b` (5 · decisions),
>   `68c5677e-c36a-4e0a-82ad-d0de8056e225` (6 · reading list).
>   Until archived, each title will appear **twice** (stale + fresh) in the LIS project pages.

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
