---
name: pin-bump
description: Land a submodule change through the two-level (component → umbrella) or three-level (plugins fork → core → umbrella) PR chain, with the merge-verification and cleanup gotchas that have each caused a real incident. Use when bumping the core/openelis, edge/drivers, or deploy/kit pins, shipping plugin changes, or merging any stacked/worktree PR in this project.
---

# pin-bump — landing submodule changes safely

## The chains

- **Two-level (normal):** component PR (bridge/kit/core repo) merges first → umbrella PR
  advances the pin (`git -C <submodule> fetch && git -C <submodule> checkout <merge-sha>`,
  then stage the pointer) → umbrella PR reviewed + merged.
- **Three-level (plugins):** `aiLabSolution/openelisglobal-plugins` fork PR (base
  `develop`) → core `OpenELIS-Global-2` PR (`.gitmodules` URL + plugins pin) → umbrella
  core-pin PR. **Never squash the fork or core pin PRs** — squashing makes the pinned
  SHA unreachable. Merge-commit or rebase only.
- **Edge slices are also two-level in a second sense:** analyzer-ingestion changes land
  in BOTH the production bridge (`edge/drivers`) and the `edge/sim` mirror; sim-only is
  incomplete.

## Ordered checklist

1. **Before any commit:** fetch + rebase the slice branch; never force-push a shared
   branch. If the branch is behind main, `git merge origin/main` INTO it (fast-forward
   push) — do NOT rebase + force-push. Verify the PR diff stays clean with
   `git diff origin/main --stat`.
2. **Verify the component repo's CI is green on the exact PR head** before merging:
   `gh pr checks <n> --repo <owner>/<repo>` — every expected check must conclude
   `success`. OpenELIS core HAS CI and it has a history of failing; a failing, errored,
   or unrun expected check blocks BOTH the component merge and the pin bump, no matter
   how green local Docker-maven runs are (local tests supplement CI, never replace it;
   checkout/auth/submodule failures are red even when no tests ran). Fix and re-run CI
   or stop as blocked — never merge just because branch protection permits it.
   The bridge HAS CI (`test.yml`) — same rule as core. Kit has no CI; there the
   adversarial review is the whole gate.
3. **Merge the component PR** and verify the merge server-side (step 5) before touching
   the umbrella pin.
4. **Advance the pin to the component PR's `merge_commit_sha`** (not the branch head),
   and confirm `git -C <submodule> merge-base --is-ancestor <pin> origin/<default>`
   after a fetch. Default branches: core=main, bridge=develop, kit=main, plugins
   fork=develop. Never pin a SHA whose component PR was red or unchecked.
5. **Verify every merge via REST, not the PR page:**
   `gh api repos/<owner>/<repo>/pulls/<n> --jq '{merged,merge_commit_sha,merged_at}'`.
   GraphQL (`gh pr view`) can show stale `OPEN` right after a merge.
6. **Comment the review verdict** on the umbrella PR (audit trail for ISO traceability),
   then merge — only with that PR's own expected checks green too. Self-merge is
   allowlisted via `Bash(gh pr merge*)` — but the rule is prefix-matched, so run
   `gh pr merge ...` **standalone**, never inside a compound command.

## Gotchas (each one caused a real incident)

- **`gh pr merge` from a linked worktree** errors with `'main' is already used by
  worktree at ...` — that is only the LOCAL post-merge step failing; **the server merge
  already succeeded**. Verify via REST `.merged`, then clean up by hand:
  `git push origin --delete <branch>` → remove the worktree → `git branch -D <branch>`.
  Running the merge from a non-repo cwd (e.g. scratchpad) with `--repo <owner>/<repo>`
  skips the local step entirely.
- **Stacked PR retarget race:** never merge a child PR immediately after its base PR
  merges. GitHub retargets the child's base to main asynchronously; merging too soon
  merges the child into the now-dead-end base branch and its content NEVER reaches main
  (this happened — LIS-24/#11). Wait until the PR page shows base=main, or open a fresh
  child→main PR. Verify any "merged" claim by checking the content is actually on main:
  `git cat-file -e origin/main:<path>`.
- **Worktrees with initialized submodules can't be `git worktree remove`d** (even
  `--force`). Confirm clean status + merged, then `rm -rf <worktree>` +
  `git worktree prune`. If Docker maven ran as root, clean root-owned `target/` first:
  `docker run --rm -v <wt>:/src maven:3.9-eclipse-temurin-21 rm -rf /src/target`.
- **ADR number collisions** from concurrent merges: keep the number on the
  Accepted/compliance-cited ADR, renumber the Proposed one to the next free slot ABOVE
  all in-flight numbers, `git mv` + fix the H1 + grep-fix every reference (no
  link-checker in CI), and fold the rename into the feature PR — never a standalone
  rename PR. Sanity-check with read-only `git merge-tree --write-tree`.
- **Upstream-sync PRs** (DIGI-UW → core) need merge commits, not squash, to keep
  upstream SHAs reachable.
- **CI is non-transitive (LIS-133 / core PR #40):** a component PR can be red while an
  umbrella pin PR is green. Umbrella workflows may use `submodules: false`, sparse
  checkouts, prebuilt images, or test-skipping source builds, so they prove only their
  named deployment/configuration behavior. Inspect the component PR itself and block on
  any failed expected check, including infrastructure failures before tests.

## After landing

Log progress on the Plane issue (`python3 scripts/plane_issue.py comment LIS-NN
--body-file -` — body via stdin/file, NEVER a second positional arg), and if the slice
is closing, run the `ac-verifier` agent first.
