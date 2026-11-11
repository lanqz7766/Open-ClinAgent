#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
TEMPLATE_PATH="${ROOT_DIR}/scripts/macos/com.clinagent.segmentation-tunnel-watchdog.plist"
LABEL="com.clinagent.segmentation-tunnel-watchdog"
TARGET_DIR="${HOME}/Library/LaunchAgents"
TARGET_PATH="${TARGET_DIR}/${LABEL}.plist"
RUNTIME_ROOT="${HOME}/Library/Application Support/ClinAgent/segmentation-tunnel-watchdog"
RUNTIME_SCRIPTS_DIR="${RUNTIME_ROOT}/scripts"

usage() {
  cat <<'EOF'
Usage: install_segmentation_tunnel_watchdog.sh [install|uninstall|status]

install    Render the LaunchAgent plist into ~/Library/LaunchAgents and load it
uninstall  Unload the LaunchAgent and remove the rendered plist
status     Show whether the LaunchAgent is loaded
EOF
}

require_file() {
  local path="$1"
  local label="$2"
  if [[ ! -f "${path}" ]]; then
    echo "${label} not found: ${path}" >&2
    exit 1
  fi
}

render_plist() {
  mkdir -p "${TARGET_DIR}"
  sed "s#__REPO_ROOT__#${RUNTIME_ROOT//\#/\\#}#g" "${TEMPLATE_PATH}" > "${TARGET_PATH}"
}

render_runtime_scripts() {
  mkdir -p "${RUNTIME_SCRIPTS_DIR}"
  cp "${ROOT_DIR}/scripts/segmentation_tunnel.sh" "${RUNTIME_SCRIPTS_DIR}/segmentation_tunnel.sh"
  cp "${ROOT_DIR}/scripts/segmentation_tunnel_watchdog.sh" "${RUNTIME_SCRIPTS_DIR}/segmentation_tunnel_watchdog.sh"
  chmod +x \
    "${RUNTIME_SCRIPTS_DIR}/segmentation_tunnel.sh" \
    "${RUNTIME_SCRIPTS_DIR}/segmentation_tunnel_watchdog.sh"
}

load_agent() {
  launchctl unload "${TARGET_PATH}" >/dev/null 2>&1 || true
  launchctl load "${TARGET_PATH}"
}

unload_agent() {
  launchctl unload "${TARGET_PATH}" >/dev/null 2>&1 || true
}

show_status() {
  if launchctl list | grep -Fq "${LABEL}"; then
    echo "LaunchAgent loaded: ${LABEL}"
    echo "Plist: ${TARGET_PATH}"
    exit 0
  fi
  echo "LaunchAgent not loaded: ${LABEL}"
  echo "Expected plist: ${TARGET_PATH}"
  exit 1
}

ACTION="${1:-install}"
case "${ACTION}" in
  install)
    require_file "${TEMPLATE_PATH}" "Template plist"
    require_file "${ROOT_DIR}/scripts/segmentation_tunnel_watchdog.sh" "Watchdog script"
    require_file "${ROOT_DIR}/scripts/segmentation_tunnel.sh" "Tunnel script"
    render_runtime_scripts
    render_plist
    load_agent
    echo "Installed LaunchAgent: ${LABEL}"
    echo "Plist: ${TARGET_PATH}"
    echo "Runtime root: ${RUNTIME_ROOT}"
    echo "Log: /tmp/clinagent-segmentation-tunnel-watchdog.log"
    ;;
  uninstall)
    unload_agent
    rm -f "${TARGET_PATH}"
    rm -rf "${RUNTIME_ROOT}"
    echo "Removed LaunchAgent: ${LABEL}"
    ;;
  status)
    show_status
    ;;
  *)
    usage >&2
    exit 1
    ;;
esac
