# Public-repository PHI review

This procedure is the privacy gate before changing LIS repository visibility or attaching
any runner. It cannot prove clinical de-identification automatically: a named privacy owner
must review the candidate blobs and sign the disposition.

The protected assets and why analyzer payloads count as PHI are defined in
[`docs/compliance/threat-model.md` A1/A2](../compliance/threat-model.md#assets). Bench
runbooks require synthetic identifiers or review/redaction before sharing.

## Scope

Review all reachable history—not just the working tree—for these four repositories:

- `aiLabSolution/lis-control`, including umbrella-side `edge/sim` fixtures;
- `aiLabSolution/OpenELIS-Global-2`;
- `aiLabSolution/openelis-analyzer-bridge`; and
- `aiLabSolution/lis-deploy-kit`.

Each submodule repository is reviewed as its own repository. Do not treat the umbrella
gitlink as a scan of component history. Include every local/remote branch and tag fetched
from origin. Reflog-only and unreachable objects are not published by GitHub and are out of
this gate; if they were ever pushed, treat them as exposed and escalate.

## Produce the complete blob inventory

Run this in a fresh private evidence directory. Create fresh full mirror clones for the
review; do not accept an existing working clone, whose history may be shallow,
single-branch, or constrained by a narrow fetch refspec. Do not put extracted payloads or
the evidence directory inside a development checkout.

```bash
PHI_EVIDENCE_STORE=/absolute/path/to/approved/private/evidence-store
test "${PHI_EVIDENCE_STORE#/absolute/path/to/}" = "$PHI_EVIDENCE_STORE"
install -d -m 700 "$PHI_EVIDENCE_STORE"
EVIDENCE=$(mktemp -d -p "$PHI_EVIDENCE_STORE" lis-phi-review.XXXXXX)
chmod 700 "$EVIDENCE"
mkdir -m 700 "$EVIDENCE/mirrors"
for name in lis-control OpenELIS-Global-2 openelis-analyzer-bridge lis-deploy-kit; do
  repo="$EVIDENCE/mirrors/$name.git"
  git clone --mirror "https://github.com/aiLabSolution/$name.git" "$repo"
  test "$(git -C "$repo" rev-parse --is-shallow-repository)" = false
  git -C "$repo" fetch origin --prune --force \
    '+refs/heads/*:refs/remotes/origin/*' \
    '+refs/tags/*:refs/tags/*'
  test -n "$(git -C "$repo" for-each-ref --format='%(refname)' refs/remotes/origin)"
  git -C "$repo" rev-list --objects --all > "$EVIDENCE/$name.objects"
  git -C "$repo" cat-file --batch-check='%(objectname) %(objecttype) %(objectsize) %(rest)' \
    < "$EVIDENCE/$name.objects" > "$EVIDENCE/$name.inventory"
  awk '$2 == "blob" {print $1}' "$EVIDENCE/$name.inventory" | sort -u \
    > "$EVIDENCE/$name.blob-shas"
  rg -i ' blob [0-9]+ .*([.]((astm|hl7|csv|tsv|sql|dump|log|bin|dat|txt|json|xml|md|pcap|pcapng|png|jpe?g|gif|tiff?|pdf|zip|tar|tgz|gz|7z))|capture|fixture|message|patient|result|archive|screenshot)' \
    "$EVIDENCE/$name.inventory" > "$EVIDENCE/$name.candidates" || true
  awk '$2 == "blob" && $3 > 1048576' "$EVIDENCE/$name.inventory" \
    > "$EVIDENCE/$name.large-blobs"
done
```

The candidate and large-blob files are prioritization aids, **not the review boundary**.
The privacy owner must disposition every unique object in `*.blob-shas`, regardless of
path, extension, size, or whether a detector flags it. That includes small XML/Markdown,
screenshots and other images, packet captures, archives, generated artifacts, and payloads
embedded under innocuous paths.

This may be performed manually or with an organization-approved comprehensive detector,
provided the detector receives the bytes of every listed blob and the manifest records its
version/configuration and result per object. Unsupported, encrypted, compressed, image,
packet-capture, or otherwise unparsed content requires manual inspection or an approved
format-specific decoder; “not scanned” cannot be dispositioned as “not PHI.” Extract one
object at a time with:

```bash
git -C /absolute/path/to/repository cat-file blob <OBJECT-SHA> \
  > "$EVIDENCE/object-under-review"
```

Review for direct and quasi-identifiers, including patient/name/address/contact fields,
medical-record or accession identifiers derived from live systems, dates of birth,
clinical results tied to a person, raw `PID`/`PV1`/`OBR`/`O`/`R` payloads, screenshots,
database dumps, and archives. “Test-looking” identifiers are not automatically synthetic;
trace them to a generator or written de-identification record.

## Pass/fail and retained evidence

- **PASS** requires the named privacy owner to sign a manifest listing repository, fetched
  origin refs/SHA tips, total unique-blob count, candidate count, large-blob count, reviewer,
  date, detector/decoder versions where used, and disposition (`synthetic`,
  `de-identified`, or `not PHI`) for every object in `*.blob-shas`. The manifest's object
  count must equal `wc -l < *.blob-shas`; omissions, scan errors, unsupported formats, and
  undecoded containers are failures, not warnings.
- **FAIL** means stop the visibility/runner change. Do not merely delete the file at HEAD:
  GitHub history, forks, caches, and clones may retain it. Escalate under the privacy/breach
  process and perform owner-approved history remediation.
- Store the detailed manifest and any extracted objects only in the approved private
  validation evidence store. Post only the manifest hash, reviewer, date, covered SHA tips,
  and PASS/FAIL to LIS-280; never paste payload contents into Plane or a PR.

No self-hosted runner may be registered while any scoped repository is public, even after a
PASS. The review controls committed content; it does not make untrusted public PR code safe
to execute on an internal host.
