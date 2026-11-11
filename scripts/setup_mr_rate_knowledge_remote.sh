#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE_HOST="${CLINAGENT_MR_RATE_REMOTE_HOST:-}"
REMOTE_ROOT="${CLINAGENT_MR_RATE_REMOTE_ROOT:-}"
SOURCE_ROOT="${CLINAGENT_MR_RATE_SOURCE_ROOT:-}"
REMOTE_SERVICE="${REMOTE_ROOT}/api/mr_rate_service.py"
LOCAL_SERVICE="${ROOT_DIR}/src/clinagent/families/neuro/knowledge/mr_rate_service.py"
COHORT_SIZE="${CLINAGENT_MR_RATE_COHORT_SIZE:-16}"
BATCH_LIMIT="${CLINAGENT_MR_RATE_BATCH_LIMIT:-1}"

if [[ -z "${REMOTE_HOST}" || -z "${REMOTE_ROOT}" || -z "${SOURCE_ROOT}" ]]; then
  echo "Set CLINAGENT_MR_RATE_REMOTE_HOST, CLINAGENT_MR_RATE_REMOTE_ROOT, and CLINAGENT_MR_RATE_SOURCE_ROOT before running this script." >&2
  exit 1
fi

if [[ ! -f "${LOCAL_SERVICE}" ]]; then
  echo "Local service file not found: ${LOCAL_SERVICE}" >&2
  exit 1
fi

ssh -o ConnectTimeout=10 "${REMOTE_HOST}" "mkdir -p '${REMOTE_ROOT}/api'"
scp "${LOCAL_SERVICE}" "${REMOTE_HOST}:${REMOTE_SERVICE}"

ssh -o ConnectTimeout=10 "${REMOTE_HOST}" \
  "python3 '${REMOTE_SERVICE}' init-root --root '${REMOTE_ROOT}' --source-root '${SOURCE_ROOT}'"

ssh -o ConnectTimeout=10 "${REMOTE_HOST}" \
  "python3 '${REMOTE_SERVICE}' ingest --root '${REMOTE_ROOT}' --source-root '${SOURCE_ROOT}' --cohort-size '${COHORT_SIZE}' --cohort-only --batch-limit '${BATCH_LIMIT}'"

ssh -o ConnectTimeout=10 "${REMOTE_HOST}" \
  "'${REMOTE_ROOT}/api/stop_api.sh' >/dev/null 2>&1 || true; '${REMOTE_ROOT}/api/start_api.sh'; for _ in 1 2 3 4 5 6 7 8 9 10; do if '${REMOTE_ROOT}/api/status_api.sh'; then exit 0; fi; sleep 1; done; exit 1"
