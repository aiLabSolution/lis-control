#!/usr/bin/env bash
# LIS-50 / S4.9 — post-install FHIR DiagnosticReport read smoke.
#
# Seeds one isolated finalized result in the clean proof database, then reads it
# through OpenELIS's public FHIR R4 endpoint. The fixed UUIDs make the fixture
# safe to replace when the script is rerun against a disposable proof stack.

set -euo pipefail

BASE_URL="${BASE_URL:-https://localhost:8443/api/OpenELIS-Global}"
FHIR_USER="${FHIR_USER:-admin}"
FHIR_PASSWORD="${FHIR_PASSWORD:-adminADMIN!}"
DB_CONTAINER="${DB_CONTAINER:-openelisglobal-database}"
DB_USER="${DB_USER:-clinlims}"
DB_NAME="${DB_NAME:-clinlims}"
REPORT_UUID="${REPORT_UUID:-5a6a7750-7cb7-4d6d-9fe0-50ecb8530001}"
OBSERVATION_UUID="${OBSERVATION_UUID:-5a6a7750-7cb7-4d6d-9fe0-50ecb8530002}"
SPECIMEN_UUID="${SPECIMEN_UUID:-5a6a7750-7cb7-4d6d-9fe0-50ecb8530003}"
SAMPLE_UUID="${SAMPLE_UUID:-5a6a7750-7cb7-4d6d-9fe0-50ecb8530004}"
ACCESSION_NUMBER="${ACCESSION_NUMBER:-LIS50SMOKE000000001}"

docker exec -i "$DB_CONTAINER" psql \
  --username "$DB_USER" \
  --dbname "$DB_NAME" \
  --set ON_ERROR_STOP=1 \
  --set report_uuid="$REPORT_UUID" \
  --set observation_uuid="$OBSERVATION_UUID" \
  --set specimen_uuid="$SPECIMEN_UUID" \
  --set sample_uuid="$SAMPLE_UUID" \
  --set accession_number="$ACCESSION_NUMBER" <<'SQL'
BEGIN;

DELETE FROM clinlims.result
WHERE fhir_uuid = :'observation_uuid'::uuid;

DELETE FROM clinlims.analysis
WHERE fhir_uuid = :'report_uuid'::uuid;

DELETE FROM clinlims.sample_item
WHERE fhir_uuid = :'specimen_uuid'::uuid;

DELETE FROM clinlims.sample
WHERE fhir_uuid = :'sample_uuid'::uuid
   OR accession_number = :'accession_number';

SELECT id AS finalized_status_id
FROM clinlims.status_of_sample
WHERE status_type = 'ANALYSIS'
  AND lower(name) = 'finalized'
ORDER BY id
LIMIT 1
\gset

SELECT id AS order_status_id
FROM clinlims.status_of_sample
WHERE status_type = 'ORDER'
ORDER BY id
LIMIT 1
\gset

SELECT id AS test_id, test_section_id
FROM clinlims.test
WHERE loinc IS NOT NULL
  AND test_section_id IS NOT NULL
  AND is_active = 'Y'
ORDER BY id
LIMIT 1
\gset

SELECT id AS sample_type_id
FROM clinlims.type_of_sample
ORDER BY id
LIMIT 1
\gset

SELECT nextval('clinlims.sample_seq') AS fixture_sample_id,
       nextval('clinlims.sample_item_seq') AS fixture_sample_item_id,
       nextval('clinlims.analysis_seq') AS fixture_analysis_id,
       nextval('clinlims.result_seq') AS fixture_result_id
\gset

INSERT INTO clinlims.sample (
  id, accession_number, fhir_uuid, domain, entered_date, received_date,
  collection_date, lastupdated, status_id, is_confirmation
) VALUES (
  :fixture_sample_id, :'accession_number', :'sample_uuid'::uuid, 'H', now(), now(),
  now(), now(), :order_status_id, false
);

INSERT INTO clinlims.sample_item (
  id, fhir_uuid, sort_order, samp_id, typeosamp_id, collection_date,
  status_id, lastupdated
) VALUES (
  :fixture_sample_item_id, :'specimen_uuid'::uuid, 1, :fixture_sample_id,
  :sample_type_id, now(), :order_status_id, now()
);

INSERT INTO clinlims.analysis (
  id, fhir_uuid, sampitem_id, test_sect_id, test_id, revision, status_id,
  started_date, completed_date, released_date, is_reportable, analysis_type,
  entry_date, lastupdated
) VALUES (
  :fixture_analysis_id, :'report_uuid'::uuid, :fixture_sample_item_id,
  :test_section_id, :test_id, 1, :finalized_status_id, now(), now(), now(),
  'Y', 'ROUTINE', now(), now()
);

INSERT INTO clinlims.result (
  id, fhir_uuid, analysis_id, sort_order, is_reportable, result_type, value,
  lastupdated, significant_digits, "grouping"
) VALUES (
  :fixture_result_id, :'observation_uuid'::uuid, :fixture_analysis_id, 1,
  'Y', 'N', '98.6', now(), 1, 0
);

COMMIT;
SQL

response="$(curl --fail --silent --show-error --insecure \
  --user "$FHIR_USER:$FHIR_PASSWORD" \
  --header 'Accept: application/fhir+json' \
  "$BASE_URL/fhir/DiagnosticReport/$REPORT_UUID")"

REPORT_RESPONSE="$response" python3 - "$REPORT_UUID" "$OBSERVATION_UUID" <<'PY'
import json
import os
import sys

expected_id = sys.argv[1]
expected_observation = f"Observation/{sys.argv[2]}"
payload = json.loads(os.environ["REPORT_RESPONSE"])

if payload.get("resourceType") != "DiagnosticReport":
    raise SystemExit(f"expected DiagnosticReport, got {payload.get('resourceType')!r}")
if payload.get("id") != expected_id:
    raise SystemExit(f"expected id {expected_id}, got {payload.get('id')!r}")
if payload.get("status") != "final":
    raise SystemExit(f"expected final status, got {payload.get('status')!r}")
references = [entry.get("reference") for entry in payload.get("result") or []]
if expected_observation not in references:
    raise SystemExit(
        f"expected DiagnosticReport.result to reference {expected_observation}, "
        f"got {references!r}"
    )

print(
    "FHIR_SMOKE_OK "
    f"resourceType={payload['resourceType']} id={payload['id']} status={payload['status']}"
)
PY
