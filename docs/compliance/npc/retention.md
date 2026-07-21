# Data-retention schedule — edge outbound HIS delivery queue

- **Document status:** `[DRAFTED]` for the queue-specific technical schedule;
  `[NEEDS-HUMAN]` for the programme-wide clinical-record schedule, site
  durations, legal holds, and accountable approvals.
- **Scope:** the edge bridge's outbound HIS store-and-forward queue
  (`his_result_queue`, LIS-45/LIS-273).
- **Not in scope:** the OpenELIS clinical record of record, audit trail, QC/PT
  records, reports, inbound raw-message archive, rejected-bundle store, or
  backups. Their retention periods remain `[NEEDS-HUMAN]` and must be completed
  in the broader laboratory schedule.
- **Owners:** customer laboratory as PIC/operator; site DPO and QA approve
  nonzero overrides and the broader schedule. This draft is not legal advice or
  an approval record.

## Classification and purpose

The outbound HIS queue is a **transient transport-recovery store**, not the
clinical record of record. OpenELIS remains the authoritative clinical record;
the queue temporarily holds the exact finalized ORU^R01 needed to survive a HIS
outage and retry byte-identically. A delivered-row tombstone remains after the
full message is redacted so the bridge can continue MSH-10 duplicate and
collision detection.

Both PENDING message bodies and delivered tombstones are patient-linked data.
A digest/fingerprint and a control ID derived from an accession are
pseudonymous, not anonymous.

## Queue-specific schedule

| Data class | Retention trigger and default | Disposal / retained residue | Approval state |
|---|---|---|---|
| **PENDING ORU body** | Condition-based: retain until the destination returns a matching `MSA-1=AA`. No age-only purge is allowed because the exact stored bytes are required for durable retry. | On AA, transition to DELIVERED and apply the delivered-body rule below. Failed or ambiguous delivery remains PENDING. | `[DRAFTED]` technical rule; site outage/recovery SOP remains required. |
| **DELIVERED full ORU body** | Default deployed window: **0 ms** after AA (`delivered-retention-ms=0`). The setting is configurable but must be nonnegative. | Redact the full message while retaining the delivery tombstone/fingerprint needed for deduplication and collision detection. | `[DRAFTED]` default. **Any nonzero override requires attributable site DPO + QA approval before use.** |
| **Delivered metadata tombstone** | Duration is not selected by this draft. The tombstone remains patient-linked/pseudonymous and must not be treated as anonymous telemetry. | Retain only the minimum metadata required for duplicate/collision handling; dispose according to the approved site duration and legal-hold decision once a validated deletion design exists. | `[NEEDS-HUMAN]`: site DPO + QA must approve duration, legal-hold behavior, and disposal evidence. |
| **SQLite WAL/freelist and local recovery artifacts** | Follow the live queue rule where technically reachable. | The bridge enables SQLite `secure_delete` and truncates the WAL after eligible redaction as best-effort logical storage disposal. This is not cryptographic erase. | `[DRAFTED]` technical control; storage validation evidence pending. |
| **Backups, snapshots, and renamed corrupt-database copies** | Inherit a separately approved site backup/recovery lifecycle; they are not erased by a live-row update. | Expire and destroy through the site's backup, snapshot, incident-recovery, and media-disposal procedures. | `[NEEDS-HUMAN]`: site-specific duration, legal holds, recovery need, and destruction evidence. |

The deployed purge/checkpoint recovery sweep is one hour
(`retention-purge-interval-ms=3600000`). The zero-window delivery path redacts
immediately after AA; the sweep catches already-eligible rows after restart or
a prior interrupted/busy WAL cleanup. PENDING rows are excluded from both
paths.

## Required safeguards and go-live gate

Before any site enables `POST /api/his/results` for patient traffic, all of the
following must be evidenced:

1. The queue path is on host full-disk encryption or an encrypted persistent
   volume. Owner-only directory/file permissions (0700/0600 where POSIX is
   supported) are also required, but do not replace encryption at rest.
2. TLS protects the bridge API and the fallback `changeme` credential has been
   replaced with a site-controlled non-default secret.
3. The site DPO and QA have approved this queue entry, including any nonzero
   delivered-message window, the metadata-tombstone duration, legal holds, and
   the backup/snapshot/corrupt-copy lifecycle.
4. Access to the queue volume, backups, and recovery copies is least-privilege
   and attributable under the site's access-control and incident procedures.

The current MAGLUMI X3 site has no OpenELIS-to-bridge HIS outbound caller; this
schedule does not authorize or enable one.

## Disposal limitations

SQLite `secure_delete`, redaction, and WAL checkpoint/truncation reduce
plaintext recoverability in the active database. They cannot establish that an
ORU disappeared from storage-controller caches, copy-on-write history,
filesystem recovery areas, media remanence, backups, snapshots, exports, or a
database previously renamed during corruption recovery. Evidence must describe
the actual site filesystem and backup implementation. Do not label the live-row
operation "cryptographic erasure."

## Evidence register

| Evidence | Status |
|---|---|
| Store tests: PENDING exclusion; AA-gated transition; zero/nonzero retention boundary; restart sweep; duplicate/collision semantics after redaction | Bridge [PR #54](https://github.com/aiLabSolution/openelis-analyzer-bridge/pull/54), merged as `356bdb2`; exact-head CI [push run](https://github.com/aiLabSolution/openelis-analyzer-bridge/actions/runs/29866500454) and [PR run](https://github.com/aiLabSolution/openelis-analyzer-bridge/actions/runs/29866503122) green; independent full suite 1106/0/0/7. |
| Filesystem tests: owner-only queue directory/database permissions where POSIX is available | Bridge PR #54 exact-head CI and independent full suite above. |
| SQLite tests: `secure_delete` configured; active WAL busy-checkpoint retry before shutdown; chronological fractional timestamp cutoff; no claim beyond tested live-store behavior | Bridge PR #54 includes dedicated regressions; adversarial pass 1 reproduced both defects and pass 2 approved the fixed exact head. |
| Deployment proof: effective retention environment | Deploy-kit [PR #24](https://github.com/aiLabSolution/lis-deploy-kit/pull/24), merged as `a279b36`; rendered Compose verified 0 ms retention and 3600000 ms maintenance. |
| Site deployment proof: encrypted volume, TLS, non-default credential, backup lifecycle | `[PLACEHOLDER — site IQ/OQ evidence required]` |
| Site DPO + QA approval of nonzero override, tombstone duration, legal holds, and backup lifecycle | `[NEEDS-HUMAN]` |

## Broader schedule still required

`[NEEDS-HUMAN]` The laboratory must complete a programme/site schedule covering
the OpenELIS clinical record of record, audit/security logs, QC/PT records,
reports, analyzer raw evidence, rejected payloads, exports, backups, legal
holds, data-subject requests, and validated destruction evidence. This narrow
queue entry does not set those clinical or regulatory periods.

## Primary privacy sources

- [Republic Act No. 10173 — Data Privacy Act of 2012 (National Privacy Commission)](https://privacy.gov.ph/data-privacy-act/)
- [Implementing Rules and Regulations of the Data Privacy Act of 2012 (National Privacy Commission)](https://privacy.gov.ph/implementing-rules-regulations-data-privacy-act-2012/)
- [NPC Circular No. 2023-06 — Security of Personal Data in the Government and Private Sector (signed PDF)](https://privacy.gov.ph/wp-content/uploads/2024/03/NPC-Circular-Repeal-16-01-Signed.pdf)
