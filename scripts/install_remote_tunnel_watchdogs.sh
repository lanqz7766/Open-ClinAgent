#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

usage() {
  cat <<'EOF'
Usage: install_remote_tunnel_watchdogs.sh [install|uninstall|status]

install    Install and load both segmentation and MR-RATE LaunchAgents
uninstall  Unload and remove both LaunchAgents
status     Show the status of both LaunchAgents
EOF
}

ACTION="${1:-install}"

run_action() {
  local script_name="$1"
  echo "==> ${script_name} ${ACTION}"
  "${ROOT_DIR}/scripts/${script_name}" "${ACTION}"
  echo
}

case "${ACTION}" in
  install|uninstall|status)
    run_action "install_segmentation_tunnel_watchdog.sh"
    run_action "install_mr_rate_knowledge_tunnel_watchdog.sh"
    ;;
  *)
    usage >&2
    exit 1
    ;;
esac
