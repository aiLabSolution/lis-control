# Flip hosted CI back to private/local mode

Use this runbook only after the LIS-280 engine chain is complete. It changes repository
visibility and the live merge-evidence contract; execute it in order from a dedicated
umbrella worktree, with `gh auth status` green and an owner available.

Read [`docs/agents/ci-map.md`](../agents/ci-map.md) first. Never use a real patient or
analyzer capture as a proof artifact; public repositories expose committed PHI globally,
and a public repository must never have a self-hosted runner.

## Preconditions — stop if any fails

1. Confirm LIS-281, LIS-282, LIS-283, LIS-284, and LIS-285 are Done and their PRs are
   merged. In particular, draft PRs #164/#168 are not substitutes for landed heavy checks.
2. From an exact, clean `origin/main` umbrella checkout, confirm `local_ci.json` contains
   all 11 expected checks, every target repository has `gate_required: true`, and its mode
   is still `hosted`. Record the umbrella and component SHAs.
3. Complete the cold/warm, historical, and cleanup evidence procedures below on the
   intended worker. Every required run must meet its stated result.
4. Complete the reachable-history
   [public-repository PHI review](public-repository-phi-review.md). Retain the signed private
   manifest and post only its hash/reviewer/date/covered tips/PASS result to LIS-280.
5. Confirm no self-hosted runner is registered:

   ```bash
   gh api orgs/aiLabSolution/actions/runners
   gh api repos/aiLabSolution/lis-control/actions/runners
   gh api repos/aiLabSolution/OpenELIS-Global-2/actions/runners
   gh api repos/aiLabSolution/openelis-analyzer-bridge/actions/runners
   ```

If a prerequisite is absent or a command is ambiguous, stop. Do not improvise the mode
flip.

### Cold and warm heavy-check evidence

First prove all six landed fast checks at the exact current pins. These are current-pin
runs, not replacements for the live LIS-282 timing record:

```bash
CONTROL=$(pwd -P)
EVIDENCE_STORE=/absolute/path/to/approved/private/evidence-store
test "${EVIDENCE_STORE#/absolute/path/to/}" = "$EVIDENCE_STORE"
install -d -m 700 "$EVIDENCE_STORE"
EVIDENCE=$(mktemp -d -p "$EVIDENCE_STORE" lis-local-ci-evidence.XXXXXX)
chmod 700 "$EVIDENCE"
test -z "$(git status --porcelain=v1)"
git submodule update --init --recursive
UMBRELLA_SHA=$(git rev-parse HEAD)
CORE_SHA=$(git -C core/openelis rev-parse HEAD)
BRIDGE_SHA=$(git -C edge/drivers rev-parse HEAD)
KIT_SHA=$(git -C deploy/kit rev-parse HEAD)

python3 scripts/local_ci.py --repo aiLabSolution/lis-control \
  --commit "$UMBRELLA_SHA" --head-branch main --checkout "$CONTROL" \
  --check scripts-tests --check edge-sim --check deploy-kit-config
python3 scripts/local_ci.py --repo aiLabSolution/OpenELIS-Global-2 \
  --commit "$CORE_SHA" --head-branch main --checkout "$CONTROL/core/openelis" \
  --check core-i18n
python3 scripts/local_ci.py --repo aiLabSolution/openelis-analyzer-bridge \
  --commit "$BRIDGE_SHA" --head-branch develop --checkout "$CONTROL/edge/drivers" \
  --check bridge-tests
python3 scripts/local_ci.py --repo aiLabSolution/lis-deploy-kit \
  --commit "$KIT_SHA" --head-branch main --checkout "$CONTROL/deploy/kit" \
  --check kit-lint
```

Pass requires all six individual statuses green at those four exact SHAs.

“Cold” means the first run on a disposable worker with no prior local-CI Maven volume,
Docker build cache, or LIS images. Do **not** prune a shared worker to manufacture it.
“Warm” means the immediate second run of the **same one check**, on the same exact
checkout and worker, after its cold run succeeds. Both runs use exact-commit evidence
mode, which publishes individual statuses but cannot mint merge-gate summary evidence.

Use five separately provisioned disposable workers—one for each row. A worker must start
from the approved pristine image, run only its row's cold/warm pair, copy its evidence to
the durable private evidence store, and then be destroyed. Reusing a worker for another
row invalidates that row's cold measurement.

| Worker label | `HEAVY_CHECK` | `TARGET_REPO` | `TARGET_SHA` | `TARGET_BRANCH` | `TARGET_CHECKOUT` |
| --- | --- | --- | --- | --- | --- |
| `core-backend` | `core-backend` | `aiLabSolution/OpenELIS-Global-2` | `$CORE_SHA` | `main` | `$CONTROL/core/openelis` |
| `core-frontend` | `core-frontend` | `aiLabSolution/OpenELIS-Global-2` | `$CORE_SHA` | `main` | `$CONTROL/core/openelis` |
| `stage0-bootstrap` | `stage0-bootstrap` | `aiLabSolution/lis-control` | `$UMBRELLA_SHA` | `main` | `$CONTROL` |
| `stage4-smoke` | `stage4-smoke` | `aiLabSolution/lis-control` | `$UMBRELLA_SHA` | `main` | `$CONTROL` |
| `site-stack-smoke` | `site-stack-smoke` | `aiLabSolution/lis-control` | `$UMBRELLA_SHA` | `main` | `$CONTROL` |

On each worker, export the six literal values from exactly one table row. Define these
runtime-inventory helpers before the first run. Images are intentionally excluded because
a successful source build may warm the image cache; containers, volumes, and networks
must not leak. Seed an unrelated stopped container, network, and marker volume so the
proof also detects mutation of a known pre-existing development resource:

```bash
SENTINEL_PREFIX=lis-local-ci-foreign-sentinel
SENTINEL_CONTAINER=$SENTINEL_PREFIX-container
SENTINEL_NETWORK=$SENTINEL_PREFIX-network
SENTINEL_VOLUME=$SENTINEL_PREFIX-volume
docker network create "$SENTINEL_NETWORK"
docker volume create "$SENTINEL_VOLUME"
docker run --name "$SENTINEL_CONTAINER" --network "$SENTINEL_NETWORK" \
  -v "$SENTINEL_VOLUME:/sentinel" alpine:3.20 \
  sh -c 'printf %s foreign-development-resource > /sentinel/marker'

snapshot_runtime() {
  label=$1
  docker ps -a --no-trunc --format '{{.ID}} {{.Names}} {{.Image}} {{.Status}}' \
    | sort > "$EVIDENCE/$label.containers"
  docker volume ls --format '{{.Name}}' | sort > "$EVIDENCE/$label.volumes"
  docker network ls --format '{{.Name}}' | sort > "$EVIDENCE/$label.networks"
  docker inspect "$SENTINEL_CONTAINER" "$SENTINEL_NETWORK" "$SENTINEL_VOLUME" \
    > "$EVIDENCE/$label.sentinel-inspect.json"
  docker run --rm --network none -v "$SENTINEL_VOLUME:/sentinel:ro" alpine:3.20 \
    sha256sum /sentinel/marker > "$EVIDENCE/$label.sentinel-content.sha256"
}
assert_runtime_unchanged() {
  before=$1
  after=$2
  allowed_new_volume=${3:-}
  diff -u "$EVIDENCE/$before.containers" "$EVIDENCE/$after.containers"
  diff -u "$EVIDENCE/$before.networks" "$EVIDENCE/$after.networks"
  diff -u "$EVIDENCE/$before.sentinel-inspect.json" \
    "$EVIDENCE/$after.sentinel-inspect.json"
  diff -u "$EVIDENCE/$before.sentinel-content.sha256" \
    "$EVIDENCE/$after.sentinel-content.sha256"
  if [ -n "$allowed_new_volume" ]; then
    ! rg -Fx "$allowed_new_volume" "$EVIDENCE/$before.volumes"
    { cat "$EVIDENCE/$before.volumes"; printf '%s\n' "$allowed_new_volume"; } \
      | sort -u > "$EVIDENCE/$before.expected-volumes"
    diff -u "$EVIDENCE/$before.expected-volumes" "$EVIDENCE/$after.volumes"
  else
    diff -u "$EVIDENCE/$before.volumes" "$EVIDENCE/$after.volumes"
  fi
}
```

Run this block once per worker after the 11-check registry has landed. The baseline is
taken before that worker's first proof, and each scenario is compared immediately rather
than against a later, already-warmed snapshot:

```bash
set -o pipefail
test "$WORKER_LABEL" = "$HEAVY_CHECK"
snapshot_runtime "$WORKER_LABEL.before-cold"
/usr/bin/time -p python3 scripts/local_ci.py \
  --repo "$TARGET_REPO" --commit "$TARGET_SHA" \
  --head-branch "$TARGET_BRANCH" --checkout "$TARGET_CHECKOUT" \
  --check "$HEAVY_CHECK" 2>&1 | tee "$EVIDENCE/$WORKER_LABEL.cold.log"
snapshot_runtime "$WORKER_LABEL.after-cold"
if [ "$HEAVY_CHECK" = core-backend ]; then
  assert_runtime_unchanged "$WORKER_LABEL.before-cold" "$WORKER_LABEL.after-cold" \
    lis-local-ci-maven-repository-v1
else
  assert_runtime_unchanged "$WORKER_LABEL.before-cold" "$WORKER_LABEL.after-cold"
fi

snapshot_runtime "$WORKER_LABEL.before-warm"
/usr/bin/time -p python3 scripts/local_ci.py \
  --repo "$TARGET_REPO" --commit "$TARGET_SHA" \
  --head-branch "$TARGET_BRANCH" --checkout "$TARGET_CHECKOUT" \
  --check "$HEAVY_CHECK" 2>&1 | tee "$EVIDENCE/$WORKER_LABEL.warm.log"
snapshot_runtime "$WORKER_LABEL.after-warm"
assert_runtime_unchanged "$WORKER_LABEL.before-warm" "$WORKER_LABEL.after-warm"
```

Pass requires all five checks green in both runs, each per-check `duration_seconds` plus
the ten `/usr/bin/time` totals retained, exact SHAs unchanged, and every runtime diff
empty except the cold core-backend run's one intentional creation of
`lis-local-ci-maven-repository-v1`. That volume must then be unchanged by the warm run;
any other resource-name creation/deletion, or any sentinel configuration/content mutation,
fails. The proof does not claim to checksum arbitrary cache-volume contents. No
baseline-flake absorption may be omitted from the core status description. Record the
durable evidence directory path and its inventory hashes privately; post only hashes and
non-sensitive timing/status summaries to Plane.

### Historical Stage-4 red/green evidence

Provision a separate **sixth disposable evidence worker** from the approved pristine
image. It is not one of the five timing workers and produces no cold/warm timing claim.
Use it only for the historical red/green, timeout, and interruption sequence in this and
the next section; destroy it after its evidence has been retained. Start from the exact
current umbrella checkout, create a new durable evidence directory, and redefine the
runtime helpers in this worker's shell:

```bash
CONTROL=$(pwd -P)
EVIDENCE_STORE=/absolute/path/to/approved/private/evidence-store
test "${EVIDENCE_STORE#/absolute/path/to/}" = "$EVIDENCE_STORE"
install -d -m 700 "$EVIDENCE_STORE"
EVIDENCE=$(mktemp -d -p "$EVIDENCE_STORE" lis-local-ci-scenarios.XXXXXX)
chmod 700 "$EVIDENCE"
test -z "$(git status --porcelain=v1)"
git submodule update --init --recursive

SENTINEL_PREFIX=lis-local-ci-foreign-sentinel
SENTINEL_CONTAINER=$SENTINEL_PREFIX-container
SENTINEL_NETWORK=$SENTINEL_PREFIX-network
SENTINEL_VOLUME=$SENTINEL_PREFIX-volume
docker network create "$SENTINEL_NETWORK"
docker volume create "$SENTINEL_VOLUME"
docker run --name "$SENTINEL_CONTAINER" --network "$SENTINEL_NETWORK" \
  -v "$SENTINEL_VOLUME:/sentinel" alpine:3.20 \
  sh -c 'printf %s foreign-development-resource > /sentinel/marker'

snapshot_runtime() {
  label=$1
  docker ps -a --no-trunc --format '{{.ID}} {{.Names}} {{.Image}} {{.Status}}' \
    | sort > "$EVIDENCE/$label.containers"
  docker volume ls --format '{{.Name}}' | sort > "$EVIDENCE/$label.volumes"
  docker network ls --format '{{.Name}}' | sort > "$EVIDENCE/$label.networks"
  docker inspect "$SENTINEL_CONTAINER" "$SENTINEL_NETWORK" "$SENTINEL_VOLUME" \
    > "$EVIDENCE/$label.sentinel-inspect.json"
  docker run --rm --network none -v "$SENTINEL_VOLUME:/sentinel:ro" alpine:3.20 \
    sha256sum /sentinel/marker > "$EVIDENCE/$label.sentinel-content.sha256"
}
assert_runtime_unchanged() {
  before=$1
  after=$2
  diff -u "$EVIDENCE/$before.containers" "$EVIDENCE/$after.containers"
  diff -u "$EVIDENCE/$before.volumes" "$EVIDENCE/$after.volumes"
  diff -u "$EVIDENCE/$before.networks" "$EVIDENCE/$after.networks"
  diff -u "$EVIDENCE/$before.sentinel-inspect.json" \
    "$EVIDENCE/$after.sentinel-inspect.json"
  diff -u "$EVIDENCE/$before.sentinel-content.sha256" \
    "$EVIDENCE/$after.sentinel-content.sha256"
}
```

Images and build caches may warm across these non-timing scenarios, but each
scenario-specific container/volume/network name baseline and the sentinel's configuration
and marker digest must remain unchanged. Use clean detached core worktrees so the umbrella
and its pinned core never move:

```bash
CORE_REPO="$CONTROL/core/openelis"
CORE_RED="$EVIDENCE/core-red"
CORE_GREEN="$EVIDENCE/core-green"
git -C "$CORE_REPO" worktree add --detach "$CORE_RED" \
  3ef18a894a93b619628ab6f75e870f8afcf7733b
git -C "$CORE_REPO" worktree add --detach "$CORE_GREEN" \
  18ff1b6e2247754ef65fd798128af844d79ddb50

snapshot_runtime historical-red.before
if python3 scripts/local_ci_stack_checks.py stage4-smoke --root "$CONTROL" \
  --core-checkout "$CORE_RED" \
  --expected-core-sha 3ef18a894a93b619628ab6f75e870f8afcf7733b \
  2>&1 | tee "$EVIDENCE/stage4-historical-red.log"; then
  echo "ERROR: historical broken core unexpectedly passed" >&2
  exit 1
fi
rg -i 'circular|fhirTransformService' "$EVIDENCE/stage4-historical-red.log"
snapshot_runtime historical-red.after
assert_runtime_unchanged historical-red.before historical-red.after

snapshot_runtime historical-green.before
python3 scripts/local_ci_stack_checks.py stage4-smoke --root "$CONTROL" \
  --core-checkout "$CORE_GREEN" \
  --expected-core-sha 18ff1b6e2247754ef65fd798128af844d79ddb50 \
  2>&1 | tee "$EVIDENCE/stage4-historical-green.log"
snapshot_runtime historical-green.after
assert_runtime_unchanged historical-green.before historical-green.after

git -C "$CORE_REPO" worktree remove "$CORE_RED"
git -C "$CORE_REPO" worktree remove "$CORE_GREEN"
```

Pass requires the red run to reach the OpenELIS boot/health proof and fail for the
historical circular-startup defect—not checkout, dependency, memory, or authentication—
and the fixed SHA to finish `OK stage4-smoke`.

### Cleanup, timeout, interruption, and development-resource isolation

The current green and historical scenarios already take and compare scenario-specific
runtime inventories above. Do the same around each injected failure; a later common
baseline cannot prove that an earlier scenario preserved pre-existing resources.

```bash
snapshot_runtime timeout.before
if LIS_LOCAL_CI_TIMEOUT_SECONDS=301 \
  python3 scripts/local_ci_stack_checks.py stage0-bootstrap --root "$CONTROL" \
  2>&1 | tee "$EVIDENCE/stage0-timeout.log"; then
  echo "ERROR: injected deadline unexpectedly passed" >&2
  exit 1
fi
rg 'beginning teardown with 300s before the engine hard timeout' \
  "$EVIDENCE/stage0-timeout.log"
snapshot_runtime timeout.after
assert_runtime_unchanged timeout.before timeout.after

snapshot_runtime interruption.before
set +e
timeout --signal=INT --kill-after=330s 120s \
  python3 scripts/local_ci_stack_checks.py stage4-smoke --root "$CONTROL" \
  > "$EVIDENCE/stage4-interrupt.log" 2>&1
interrupt_rc=$?
set -e
test "$interrupt_rc" -ne 0
rg -i 'KeyboardInterrupt|received signal 2' "$EVIDENCE/stage4-interrupt.log"
snapshot_runtime interruption.after
assert_runtime_unchanged interruption.before interruption.after
test -z "$(find "$CONTROL/core/openelis" -xdev \
  \( ! -user "$(id -u)" -o ! -group "$(id -g)" \) -print -quit)"
git -C "$CONTROL" status --porcelain=v1
```

Pass requires both injected runs red for the named reason, every per-scenario diff empty,
no foreign-owned core file, and a clean umbrella checkout. The normal green and historical
red/green runs above have their own immediate teardown comparisons, so together the
evidence covers green, red, timeout, and interruption. Hash the sixth worker's evidence
inventory in the approved private store, record its private location, then destroy the
worker. Do not reuse it for a cold timing claim.

## 1. Flip the registry through a reviewed PR

Create a small umbrella PR that changes only `local_ci.json` from `"mode": "hosted"` to
`"mode": "local"`. From the exact, clean PR checkout, run the engine against the PR:

```bash
python3 scripts/local_ci.py <MODE-FLIP-PR> \
  --repo aiLabSolution/lis-control \
  --checkout /absolute/path/to/the/exact/pr/worktree
gh api repos/aiLabSolution/lis-control/commits/<EXACT-HEAD>/status
```

Require `local-ci/summary=success` on that exact head plus every hosted check selected by
the PR. Merge without an override, verify the server-side merge, fetch `origin/main`, and
confirm the landed registry says `local`.

## 2. Disable hosted Actions

First inventory the reproducible pre-flip state. These durable files contain workflow
IDs, paths, and active/disabled state and are the authoritative re-enable record. Keep
the complete API inventory for audit, but create a separate replay file containing only
real `.github/workflows/**` files; GitHub-managed `dynamic/**` entries have no file that
`gh workflow enable` can resolve.

```bash
for repo in lis-control OpenELIS-Global-2 openelis-analyzer-bridge lis-deploy-kit; do
  gh api "repos/aiLabSolution/$repo/actions/workflows" --paginate \
    --jq '.workflows[] | [.id,.path,.state] | @tsv' \
    | sort > "$EVIDENCE/$repo.workflows.before"
  awk -F '\t' '$2 ~ /^\.github\/workflows\//' \
    "$EVIDENCE/$repo.workflows.before" \
    > "$EVIDENCE/$repo.workflows.replay"
done
```

Disable the upstream-owned schedules explicitly before disabling repository Actions.
Their job-level repository gates make them no-ops on LabSolution today, but their disabled
state must survive a later repository-level re-enable:

```bash
gh workflow disable tx-pull.yml --repo aiLabSolution/OpenELIS-Global-2
gh workflow disable e2e-cache-cleanup.yml --repo aiLabSolution/OpenELIS-Global-2
```

Now disable Actions at repository level. This is deliberate: it stops mapped merge CI,
unmapped documentation automation, workflow-run chains, image publication, and inherited
upstream no-ops without needing a fragile per-file list. Local commit-status publication
does not use Actions.

```bash
for repo in lis-control OpenELIS-Global-2 openelis-analyzer-bridge lis-deploy-kit; do
  gh api --method PUT "repos/aiLabSolution/$repo/actions/permissions" -F enabled=false
  test "$(gh api "repos/aiLabSolution/$repo/actions/permissions" --jq .enabled)" = false
done
```

Record the four successful permission reads, durable private evidence location, and hashes
of both workflow files for each repository on LIS-280. The files themselves must remain in
the approved private evidence store through hosted-mode restoration; hashes alone cannot
reconstruct workflow state. Do not post workflow logs, tokens, or payload evidence.

## 3. Make the temporary public repositories private

At the 2026-07-19 snapshot, deploy-kit is already private. Change only the other three:

```bash
gh repo edit aiLabSolution/lis-control --visibility private \
  --accept-visibility-change-consequences
gh repo edit aiLabSolution/OpenELIS-Global-2 --visibility private \
  --accept-visibility-change-consequences
gh repo edit aiLabSolution/openelis-analyzer-bridge --visibility private \
  --accept-visibility-change-consequences
```

Re-query visibility, classic branch protection, and rulesets:

```bash
for repo in lis-control OpenELIS-Global-2 openelis-analyzer-bridge lis-deploy-kit; do
  gh repo view "aiLabSolution/$repo" --json visibility,defaultBranchRef \
    > "$EVIDENCE/$repo.visibility.after"
  default_branch=$(gh repo view "aiLabSolution/$repo" --json defaultBranchRef \
    --jq .defaultBranchRef.name)
  gh api "repos/aiLabSolution/$repo/branches/$default_branch/protection" \
    > "$EVIDENCE/$repo.protection.after" 2>&1 || true
  gh api "repos/aiLabSolution/$repo/rulesets" \
    > "$EVIDENCE/$repo.rulesets.after" 2>&1 || true
done
```

Pass requires all four visibility reads to say `PRIVATE`. Protection/ruleset HTTP 403 or
404 is **not** a pass by silence. Stop unless either (a) the default branch still has an
active server-side rule preventing direct/non-fast-forward updates and deletion, or (b)
the repository owner records an explicit, time-bounded compensating-control approval on
LIS-280 naming: PR-only changes, `.githooks` installed on every authorized operator clone,
no direct/force push, exact-head review, and a date to restore server-side protection.
The local hook is mandatory but is not itself a server-side control.

## 4. Refresh check-poisoned PR heads

Failed-to-start hosted check runs remain attached to their old SHA. For each open PR,
inspect the exact head. If it carries quota/visibility-poisoned runs, first verify that the
head repository owner is `aiLabSolution`, the PR is not cross-repository, and a reviewer
has inspected the diff. Local CI executes PR-controlled code with worker access: never run
it on an external fork or an unreviewed change to `scripts/`, `.githooks/`, workflow files,
or the local-CI registry.

```bash
gh pr view <PR> --repo <OWNER/REPO> \
  --json headRefOid,headRepositoryOwner,isCrossRepository,files
gh pr diff <PR> --repo <OWNER/REPO>
```

Then update the branch. If it is behind its default branch, merge the default branch and
push:

```bash
git fetch origin
git merge origin/<default-branch>
git push origin HEAD
```

If it is already current, create only the traceable empty commit and push:

```bash
git merge-base --is-ancestor origin/<default-branch> HEAD
git commit --allow-empty -m "ci: refresh exact head after private-mode flip"
git push origin HEAD
```

Run the engine from an exact trusted umbrella checkout; component repositories do not
contain the runner or registry. Choose exactly one command matching the refreshed PR and
point `--checkout` at that PR's exact clean worktree:

```bash
RUNNER_CONTROL=/absolute/path/to/trusted/exact/umbrella-main
python3 "$RUNNER_CONTROL/scripts/local_ci.py" <PR> \
  --repo aiLabSolution/lis-control \
  --checkout /absolute/path/to/exact/lis-control-pr-worktree
python3 "$RUNNER_CONTROL/scripts/local_ci.py" <PR> \
  --repo aiLabSolution/OpenELIS-Global-2 \
  --checkout /absolute/path/to/exact/openelis-pr-worktree
python3 "$RUNNER_CONTROL/scripts/local_ci.py" <PR> \
  --repo aiLabSolution/openelis-analyzer-bridge \
  --checkout /absolute/path/to/exact/bridge-pr-worktree
python3 "$RUNNER_CONTROL/scripts/local_ci.py" <PR> \
  --repo aiLabSolution/lis-deploy-kit \
  --checkout /absolute/path/to/exact/deploy-kit-pr-worktree
```

Before execution, verify `RUNNER_CONTROL` is clean and at the recorded trusted umbrella
SHA, and verify each component worktree HEAD equals the refreshed `headRefOid`. Old green
evidence never transfers to the refreshed SHA.

## 5. Prove one end-to-end local-evidence merge

Open a throwaway umbrella PR with a harmless, traceable change under `scripts/` so the
registry selects `scripts-tests`. From its exact clean checkout:

```bash
gh pr view <THROWAWAY-PR> --repo aiLabSolution/lis-control \
  --json headRefOid,headRepositoryOwner,isCrossRepository,files
gh pr diff <THROWAWAY-PR> --repo aiLabSolution/lis-control
python3 scripts/local_ci.py <THROWAWAY-PR> \
  --repo aiLabSolution/lis-control \
  --checkout /absolute/path/to/the/exact/pr/worktree
gh pr view <THROWAWAY-PR> --repo aiLabSolution/lis-control \
  --json headRefOid,statusCheckRollup
gh pr merge <THROWAWAY-PR> --repo aiLabSolution/lis-control --merge
gh api repos/aiLabSolution/lis-control/pulls/<THROWAWAY-PR> \
  --jq '{merged,merge_commit_sha}'
```

The exact head must show `local-ci/summary=success`, the normal path-selected individual
statuses must be green, the merge must succeed without override, and REST must report
`merged: true`. Remove the throwaway branch/worktree and record the proof on LIS-280.

## Re-enable hosted mode safely

Use this only after Actions capacity is funded/restored or the repositories are made
public again after a fresh PHI/self-hosted-runner review.

1. Resolve capacity/visibility first. Enabling workflows while private quota is still
   exhausted recreates poisoned check runs.
2. Keep registry mode `local` while enabling repository Actions. Retrieve and hash-verify
   the four durable `*.workflows.replay` inventories, then restore their states except for
   the two schedules in step 3. Handle GitHub-managed `dynamic/**` policies separately
   through the repository security/settings controls that created them; never pass a
   dynamic path to `gh workflow enable` or `disable`.
   At minimum, explicitly enable the six umbrella workflows and the component
   `backend.yml`, `frontend.yml`, `i18n-check.yml`, and `test.yml`.

   ```bash
   for repo in lis-control OpenELIS-Global-2 openelis-analyzer-bridge lis-deploy-kit; do
     gh api --method PUT "repos/aiLabSolution/$repo/actions/permissions" -F enabled=true
     test "$(gh api "repos/aiLabSolution/$repo/actions/permissions" --jq .enabled)" = true
     while IFS=$'\t' read -r workflow_id workflow_path state; do
       case "$workflow_path" in
         *tx-pull.yml|*e2e-cache-cleanup.yml) continue ;;
       esac
       if [ "$state" = active ]; then
         gh api --method PUT \
           "repos/aiLabSolution/$repo/actions/workflows/$workflow_id/enable"
       else
         gh api --method PUT \
           "repos/aiLabSolution/$repo/actions/workflows/$workflow_id/disable"
       fi
     done < "$EVIDENCE/$repo.workflows.replay"
   done
   ```

   The complete `*.workflows.before` inventory still records `dynamic/**` entries (for
   example GitHub-managed CodeQL/dependency-graph workflows), but the replay file excludes
   them. Repository Actions permission and their originating security setting govern them.
3. **Do not re-enable `tx-pull.yml` or `e2e-cache-cleanup.yml` on LabSolution.** They are
   upstream-repository schedules. Re-enable only after removing the DIGI-UW gate and
   explicitly accepting ownership, secrets, retention, and schedule.
4. Open a proof PR and require every path-selected hosted check green on its exact head;
   local mode still requires `local-ci/summary` during this overlap.
5. Through a reviewed umbrella PR, change the registry to `hosted`. The mode authority is
   the exact PR checkout, so hosted rules are normative for this transition head. As a
   stricter transition policy, require **both** every selected hosted check and a successful
   supplemental `local-ci/summary` produced by running the engine on that same exact head.
   Merge without override and confirm the landed file.
6. Open one more normal PR. Require the expected hosted checks on the exact head and prove
   the merge without a local summary. Only then retire the overlap proof artifacts.

At every step, an absent expected check is red. Visibility, a green sibling repository,
or GitHub permitting a merge never waives that rule.
