#!/usr/bin/env bash
# Submit a Wippersnapper_Python non-hardware test run to the HIL controller.
#
# Usage:
#   GH_PAT=ghp_xxx HIL_API_TOKEN=your-token bash scripts/submit-wipper-test.sh
#
# Optional overrides:
#   HIL_API_BASE    default: http://localhost:8080
#   WIPPER_REF      git ref to test, default: main
#   PYTEST_MARKERS  pytest -m expression, default: "not hardware"

set -euo pipefail

: "${GH_PAT:?Set GH_PAT to a GitHub personal access token with repo read scope}"
: "${HIL_API_TOKEN:?Set HIL_API_TOKEN to a HIL controller bearer token}"

HIL_API_BASE="${HIL_API_BASE:-http://localhost:8080}"
WIPPER_REF="${WIPPER_REF:-main}"
PYTEST_MARKERS="${PYTEST_MARKERS:-not hardware}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JOB_TEMPLATE="${SCRIPT_DIR}/../examples/wippersnapper-python/job.json"

# Substitute placeholders into a temp file
tmp_job=$(mktemp /tmp/hil-wipper-job-XXXXXX.json)
trap 'rm -f "$tmp_job"' EXIT

jq \
  --arg pat "$GH_PAT" \
  --arg ref "$WIPPER_REF" \
  --argjson markers "$(jq -n --arg m "$PYTEST_MARKERS" '["-m", $m, "-v", "--tb=short"]')" \
  '.payload.source.pat = $pat | .payload.source.ref = $ref | .params.args = $markers' \
  "$JOB_TEMPLATE" > "$tmp_job"

echo "Submitting job (ref=${WIPPER_REF}, markers=\"${PYTEST_MARKERS}\")..."

HIL_API_BASE="$HIL_API_BASE" \
HIL_API_TOKEN="$HIL_API_TOKEN" \
HIL_JOB_JSON="$tmp_job" \
  bash "${SCRIPT_DIR}/../examples/hil-call.sh"
