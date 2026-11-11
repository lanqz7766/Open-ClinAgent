#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOCAL_PORT="${CLINAGENT_SEGMENTATION_LOCAL_PORT:-18000}"
HEALTH_URL="http://127.0.0.1:${LOCAL_PORT}/health"
LOCK_DIR="${TMPDIR:-/tmp}/clinagent-segmentation-tunnel-watchdog.lock"
LOG_PREFIX="[clinagent-seg-watchdog]"

log() {
  printf "%s %s\n" "${LOG_PREFIX}" "$*"
}

cleanup() {
  rmdir "${LOCK_DIR}" >/dev/null 2>&1 || true
}

if ! mkdir "${LOCK_DIR}" >/dev/null 2>&1; then
  exit 0
fi
trap cleanup EXIT

cd "${ROOT_DIR}"

if curl -fsS "${HEALTH_URL}" >/dev/null 2>&1; then
  log "tunnel healthy on localhost:${LOCAL_PORT}"
  exit 0
fi

log "tunnel unhealthy on localhost:${LOCAL_PORT}; restarting"
"${ROOT_DIR}/scripts/segmentation_tunnel.sh" restart

if curl -fsS "${HEALTH_URL}" >/dev/null 2>&1; then
  log "tunnel recovered"
  exit 0
fi

log "tunnel restart failed"
exit 1
