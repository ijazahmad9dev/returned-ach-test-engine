#!/usr/bin/env bash
# ==============================================================================
# Return ACH Test Engine - Post-Deployment Gate & Client Evidence Script (Phase 4)
# ==============================================================================
# Usage:
#   ./scripts/deploy_gate.sh
#
# Environment variables:
#   RUNTIME_URL   (default: http://localhost:8000)
#   UI_URL        (default: http://localhost:3000)
#   OUTPUT_DIR    (default: reports/gate)
#   HEADLESS      (default: true)
#   FAIL_FAST     (default: false)
#   MAX_WAIT_SEC  (default: 60)
# ==============================================================================

set -euo pipefail

RUNTIME_URL="${RUNTIME_URL:-http://localhost:8000}"
UI_URL="${UI_URL:-http://localhost:3000}"
OUTPUT_DIR="${OUTPUT_DIR:-reports/gate}"
HEADLESS="${HEADLESS:-true}"
FAIL_FAST="${FAIL_FAST:-false}"
MAX_WAIT_SEC="${MAX_WAIT_SEC:-60}"

echo "========================================================================"
echo " Return ACH Test Engine: Phase 4 Post-Deployment Gate"
echo "========================================================================"
echo "Runtime API:       ${RUNTIME_URL}"
echo "Control Center UI: ${UI_URL}"
echo "Output Directory:  ${OUTPUT_DIR}"
echo "========================================================================"

# Step 1: Wait for services to be reachable
echo "[1/3] Waiting for target services readiness (max ${MAX_WAIT_SEC}s)..."
start_time=$(date +%s)
ready=false

while true; do
  current_time=$(date +%s)
  elapsed=$((current_time - start_time))

  if [ "${elapsed}" -ge "${MAX_WAIT_SEC}" ]; then
    echo "❌ ERROR: Target services did not become ready within ${MAX_WAIT_SEC}s."
    exit 1
  fi

  api_status=$(curl -s -o /dev/null -w "%{http_code}" "${RUNTIME_URL}/api/v1/health" || true)
  ui_status=$(curl -s -o /dev/null -w "%{http_code}" "${UI_URL}" || true)

  if [ "${api_status}" = "200" ] && [ "${ui_status}" = "200" ]; then
    echo "✓ Both Runtime API (${RUNTIME_URL}) and Control Center UI (${UI_URL}) are UP (200 OK)."
    ready=true
    break
  fi

  echo "  Waiting... API HTTP: ${api_status}, UI HTTP: ${ui_status} (${elapsed}s elapsed)"
  sleep 3
done

# Step 2: Execute Deployment Gate
echo ""
echo "[2/3] Executing 100% Real-User Journey Evaluation & Gate..."

GATE_ARGS=(
  "gate"
  "--url" "${RUNTIME_URL}"
  "--ui-url" "${UI_URL}"
  "--output-dir" "${OUTPUT_DIR}"
  "--bundle-client-report"
)

if [ "${HEADLESS}" = "true" ]; then
  GATE_ARGS+=("--headless")
else
  GATE_ARGS+=("--no-headless")
fi

if [ "${FAIL_FAST}" = "true" ]; then
  GATE_ARGS+=("--fail-fast")
fi

set +e
uv run ach-test "${GATE_ARGS[@]}"
GATE_EXIT_CODE=$?
set -e

# Step 3: Handle Gate Outcome
echo ""
echo "[3/3] Evaluating Deployment Gate Verdict..."
if [ "${GATE_EXIT_CODE}" -eq 0 ]; then
  echo "========================================================================"
  echo " 🎉 DEPLOYMENT GATE: APPROVED (GREEN DEPLOY)"
  echo "========================================================================"
  echo "All 8 real-user journeys passed."
  echo "Client deliverables package available at: ${OUTPUT_DIR}/client_package/"
  echo "Interactive HTML Report: ${OUTPUT_DIR}/client_package/index.html"
  echo "Evidence Manifest:       ${OUTPUT_DIR}/client_package/evidence_manifest.json"
  echo "========================================================================"
  exit 0
else
  echo "========================================================================"
  echo " 🚨 DEPLOYMENT GATE: REJECTED (RED DEPLOY)"
  echo "========================================================================"
  echo "Deployment gate detected failures or regressions."
  echo "Diagnostic Report: ${OUTPUT_DIR}/red_deploy_failure.json"
  echo "Markdown Details:  ${OUTPUT_DIR}/red_deploy_failure.md"
  echo "Halting deployment pipeline with exit code 1."
  echo "========================================================================"
  exit "${GATE_EXIT_CODE}"
fi
