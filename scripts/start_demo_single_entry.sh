#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${CLINAGENT_SINGLE_ENTRY_PORT:-3000}"
PYTHON_BIN="${CLINAGENT_PYTHON_BIN:-}"

detect_python() {
  if [[ -n "${PYTHON_BIN}" && -x "${PYTHON_BIN}" ]]; then
    echo "${PYTHON_BIN}"
    return 0
  fi
  local candidates=(
    "${ROOT_DIR}/.venv/bin/python"
    "$(command -v python3 || true)"
  )
  for candidate in "${candidates[@]}"; do
    if [[ -n "${candidate}" && -x "${candidate}" ]]; then
      echo "${candidate}"
      return 0
    fi
  done
  echo "python3"
}

detect_structural_root() {
  local candidates=(
    "${CLINAGENT_NEURO_REPORT_DATA_ROOT:-}"
    "${ROOT_DIR}/.clinagent/local/longitudinal_patient"
    "${ROOT_DIR}/../Data/longitudinal_patient"
    "${HOME}/Documents/Agent/Data/longitudinal_patient"
  )
  local base
  for base in "${candidates[@]}"; do
    [[ -z "${base}" ]] && continue
    if [[ -f "${base}/metadata/longitudinal_manifest.csv" ]]; then
      echo "${base}"
      return 0
    fi
  done
  local search_bases=(
    "${ROOT_DIR}/../Data"
    "${HOME}/Documents/Agent/Data"
  )
  local child
  for base in "${search_bases[@]}"; do
    [[ -d "${base}" ]] || continue
    while IFS= read -r -d '' child; do
      if [[ -f "${child}/metadata/longitudinal_manifest.csv" ]]; then
        echo "${child}"
        return 0
      fi
    done < <(find "${base}" -maxdepth 2 -type d -print0)
  done
  return 1
}

detect_response_root() {
  local candidates=(
    "${CLINAGENT_NEURO_LONGITUDINAL_DATA_ROOT:-}"
    "${ROOT_DIR}/.clinagent/demo_data/proteas"
    "${ROOT_DIR}/../Data"
    "${HOME}/Documents/Agent/Data"
  )
  local base
  for base in "${candidates[@]}"; do
    [[ -z "${base}" ]] && continue
    if [[ -f "${base}/PROTEAS-Clinical_and_demographic_data.xlsx" && -f "${base}/PROTEAS-MRI_radiomics_data.xlsx" ]]; then
      echo "${base}"
      return 0
    fi
    if [[ -d "${base}" ]]; then
      local child
      while IFS= read -r -d '' child; do
        if [[ -f "${child}/PROTEAS-Clinical_and_demographic_data.xlsx" && -f "${child}/PROTEAS-MRI_radiomics_data.xlsx" ]]; then
          echo "${child}"
          return 0
        fi
      done < <(find "${base}" -maxdepth 2 -type d -print0)
    fi
  done
  return 1
}

PYTHON_EXEC="$(detect_python)"
STRUCTURAL_ROOT="$(detect_structural_root || true)"
RESPONSE_ROOT="$(detect_response_root || true)"

if [[ -z "${STRUCTURAL_ROOT}" ]]; then
  echo "[clinagent] structural preload root not found" >&2
  exit 1
fi

if [[ -z "${RESPONSE_ROOT}" ]]; then
  echo "[clinagent] response preload root not found" >&2
  exit 1
fi

cd "${ROOT_DIR}"

./scripts/segmentation_tunnel.sh start
./scripts/mr_rate_knowledge_tunnel.sh start

echo "[clinagent] building frontend for single-entry /demo"
(cd frontend && npm run build >/dev/null)

export CLINAGENT_NEURO_REPORT_DATA_ROOT="${STRUCTURAL_ROOT}"
export CLINAGENT_NEURO_LONGITUDINAL_DATA_ROOT="${RESPONSE_ROOT}"
export CLINAGENT_NNUNET_SERVICE_URL="${CLINAGENT_NNUNET_SERVICE_URL:-http://127.0.0.1:18000}"
export CLINAGENT_SEGMENTATION_TOOL_GPU_ID="${CLINAGENT_SEGMENTATION_TOOL_GPU_ID:-0}"
export CLINAGENT_MR_RATE_BASE_URL="${CLINAGENT_MR_RATE_BASE_URL:-http://127.0.0.1:18120}"
export PYTHONPATH="${ROOT_DIR}/src"

echo "[clinagent] structural preload root: ${STRUCTURAL_ROOT}"
echo "[clinagent] response preload root: ${RESPONSE_ROOT}"
echo "[clinagent] segmentation service: ${CLINAGENT_NNUNET_SERVICE_URL}"
echo "[clinagent] MR-RATE knowledge service: ${CLINAGENT_MR_RATE_BASE_URL}"
echo "[clinagent] starting single-entry demo on http://127.0.0.1:${PORT}/demo"

exec "${PYTHON_EXEC}" - <<'PY'
import os
import sys

from clinagent.__main__ import main
from clinagent.families.neuro.report_demo import NeuroReportDemoStore

store = NeuroReportDemoStore()
status = store.get_preload_status()
print(
  f"[clinagent] preload summary: structural_patients={status['structural_patient_count']} "
  f"response_cases={status['response_case_count']} examples={status['example_count']}"
)
if status["warnings"]:
  print(f"[clinagent] preload warnings: {', '.join(status['warnings'])}")

sys.argv = ["clinagent", "--serve", "--port", os.getenv("CLINAGENT_SINGLE_ENTRY_PORT", "3000")]
main()
PY
