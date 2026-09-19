#!/usr/bin/env bash
# Phase 1 seed loader (HANDOFF.md build order step 1). Loads every
# Synthea-generated FHIR R4 transaction bundle into the Cloud Healthcare
# API FHIR store via executeBundle. Idempotent-ish: Synthea bundles use
# conditional-create (ifNoneExist) internally, so re-running is safe.
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-prior-auth-fhir-demo}"
LOCATION="${LOCATION:-us-central1}"
DATASET="${DATASET:-prior-auth-dataset}"
FHIR_STORE="${FHIR_STORE:-prior-auth-fhir-store}"
BUNDLE_DIR="${BUNDLE_DIR:-$(dirname "$0")/../synthea/output/fhir}"

BASE_URL="https://healthcare.googleapis.com/v1/projects/${PROJECT_ID}/locations/${LOCATION}/datasets/${DATASET}/fhirStores/${FHIR_STORE}/fhir"
TOKEN="$(gcloud auth print-access-token)"

count=0
fail=0
# hospitalInformation*.json and practitionerInformation*.json define the
# Organization/Practitioner resources that per-patient bundles reference
# via conditional (ifNoneExist) references — they must exist in the store
# before those references can resolve, so load them first.
ordered_files=$(
  { ls "$BUNDLE_DIR"/hospitalInformation*.json 2>/dev/null; \
    ls "$BUNDLE_DIR"/practitionerInformation*.json 2>/dev/null; \
    ls "$BUNDLE_DIR"/*.json 2>/dev/null | grep -v -E 'hospitalInformation|practitionerInformation'; }
)

for bundle in $ordered_files; do
  name=$(basename "$bundle")

  status=$(curl -s -o /tmp/fhir_load_response.json -w "%{http_code}" \
    -X POST "${BASE_URL}" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/fhir+json" \
    --data-binary "@${bundle}")

  if [[ "$status" == "200" ]]; then
    count=$((count + 1))
  else
    fail=$((fail + 1))
    echo "FAILED (${status}): ${name}" >&2
    head -c 500 /tmp/fhir_load_response.json >&2
    echo >&2
  fi
done

echo "Loaded ${count} bundles, ${fail} failed."
