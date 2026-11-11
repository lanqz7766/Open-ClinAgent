#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-start}"
LOCAL_PORT="${CLINAGENT_SEGMENTATION_LOCAL_PORT:-18000}"
REMOTE_PORT="${CLINAGENT_SEGMENTATION_REMOTE_PORT:-18000}"
REMOTE_HOST="${CLINAGENT_SEGMENTATION_REMOTE_HOST:-${CLINAGENT_SEGMENTATION_TOOL_REMOTE_HOST:-}}"
TMUX_SESSION="${CLINAGENT_SEGMENTATION_TMUX_SESSION:-clinagent-seg-tunnel}"
HEALTH_URL="http://127.0.0.1:${LOCAL_PORT}/health"
MAX_WAIT_SECONDS="${CLINAGENT_SEGMENTATION_TUNNEL_WAIT_SECONDS:-12}"

port_listening() {
  lsof -iTCP:"${LOCAL_PORT}" -sTCP:LISTEN -n -P >/dev/null 2>&1
}

tmux_session_exists() {
  command -v tmux >/dev/null 2>&1 || return 1
  tmux has-session -t "${TMUX_SESSION}" >/dev/null 2>&1
}

use_tmux() {
  command -v tmux >/dev/null 2>&1
}

health_ok() {
  curl -fsS "${HEALTH_URL}" >/dev/null 2>&1
}

wait_for_health() {
  local attempt=0
  while (( attempt < MAX_WAIT_SECONDS )); do
    if health_ok; then
      return 0
    fi
    sleep 1
    attempt=$((attempt + 1))
  done
  return 1
}

start_tunnel() {
  if [[ -z "${REMOTE_HOST}" ]]; then
    echo "Set CLINAGENT_SEGMENTATION_REMOTE_HOST or CLINAGENT_SEGMENTATION_TOOL_REMOTE_HOST before starting the tunnel." >&2
    exit 1
  fi

  if port_listening; then
    if health_ok; then
      echo "Segmentation tunnel already running in tmux session '${TMUX_SESSION}'."
      echo "Health: ${HEALTH_URL}"
      return 0
    fi
  fi

  if tmux_session_exists || port_listening; then
    echo "Existing tunnel session '${TMUX_SESSION}' looks stale. Restarting it."
    tmux kill-session -t "${TMUX_SESSION}" >/dev/null 2>&1 || true
    lsof -tiTCP:"${LOCAL_PORT}" -sTCP:LISTEN | xargs -r kill >/dev/null 2>&1 || true
    sleep 1
  fi

  echo "Starting segmentation tunnel in tmux session '${TMUX_SESSION}'"
  echo "Forward: localhost:${LOCAL_PORT} -> ${REMOTE_HOST}:127.0.0.1:${REMOTE_PORT}"

  if use_tmux; then
    tmux new-session -d -s "${TMUX_SESSION}" \
      "exec ssh -o ExitOnForwardFailure=yes -o ConnectTimeout=10 -o ServerAliveInterval=60 -o ServerAliveCountMax=3 -N -L ${LOCAL_PORT}:127.0.0.1:${REMOTE_PORT} ${REMOTE_HOST}"
  else
    echo "tmux not found; using background ssh fallback."
    ssh -f -o ExitOnForwardFailure=yes -o ConnectTimeout=10 -o ServerAliveInterval=60 -o ServerAliveCountMax=3 \
      -N -L "${LOCAL_PORT}:127.0.0.1:${REMOTE_PORT}" "${REMOTE_HOST}"
  fi

  if wait_for_health; then
    echo "Tunnel ready."
    echo "Health: ${HEALTH_URL}"
    return 0
  fi

  echo "Tunnel failed to become healthy within ${MAX_WAIT_SECONDS}s." >&2
  echo "Use 'tmux attach -t ${TMUX_SESSION}' to inspect the session output." >&2
  exit 1
}

stop_tunnel() {
  if ! tmux_session_exists && ! port_listening; then
    echo "Segmentation tunnel is not running."
    return 0
  fi

  tmux kill-session -t "${TMUX_SESSION}" >/dev/null 2>&1 || true
  lsof -tiTCP:"${LOCAL_PORT}" -sTCP:LISTEN | xargs -r kill >/dev/null 2>&1 || true
  echo "Stopped segmentation tunnel session '${TMUX_SESSION}'."
}

status_tunnel() {
  if ! port_listening; then
    echo "Segmentation tunnel is not running."
    exit 1
  fi

  echo "Segmentation tunnel is running on localhost:${LOCAL_PORT}."
  if health_ok; then
    echo "Health: OK (${HEALTH_URL})"
    curl -sS "${HEALTH_URL}"
  else
    echo "Health: FAILED (${HEALTH_URL})" >&2
    exit 1
  fi
}

logs_tunnel() {
  if tmux_session_exists; then
    echo "Attach with: tmux attach -t ${TMUX_SESSION}"
    return 0
  fi

  if port_listening; then
    echo "Tunnel is running without tmux; no session logs are available."
    return 0
  fi

  echo "Segmentation tunnel is not running."
  exit 1
}

case "${ACTION}" in
  start) start_tunnel ;;
  stop) stop_tunnel ;;
  restart)
    stop_tunnel || true
    start_tunnel
    ;;
  status) status_tunnel ;;
  logs) logs_tunnel ;;
  *)
    echo "Usage: $0 {start|stop|restart|status|logs}" >&2
    exit 1
    ;;
esac
