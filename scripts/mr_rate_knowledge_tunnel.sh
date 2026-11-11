#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-start}"
LOCAL_PORT="${CLINAGENT_MR_RATE_LOCAL_PORT:-18120}"
REMOTE_PORT="${CLINAGENT_MR_RATE_REMOTE_PORT:-18120}"
REMOTE_HOST="${CLINAGENT_MR_RATE_REMOTE_HOST:-}"
TMUX_SESSION="${CLINAGENT_MR_RATE_TMUX_SESSION:-clinagent-mr-rate-tunnel}"
HEALTH_URL="http://127.0.0.1:${LOCAL_PORT}/health"
MAX_WAIT_SECONDS="${CLINAGENT_MR_RATE_TUNNEL_WAIT_SECONDS:-12}"

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
    echo "Set CLINAGENT_MR_RATE_REMOTE_HOST before starting the MR-RATE tunnel." >&2
    exit 1
  fi

  if port_listening && health_ok; then
    echo "MR-RATE knowledge tunnel already running in tmux session '${TMUX_SESSION}'."
    echo "Health: ${HEALTH_URL}"
    return 0
  fi

  if tmux_session_exists || port_listening; then
    tmux kill-session -t "${TMUX_SESSION}" >/dev/null 2>&1 || true
    lsof -tiTCP:"${LOCAL_PORT}" -sTCP:LISTEN | xargs -r kill >/dev/null 2>&1 || true
    sleep 1
  fi

  echo "Starting MR-RATE knowledge tunnel in tmux session '${TMUX_SESSION}'"
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
  tmux kill-session -t "${TMUX_SESSION}" >/dev/null 2>&1 || true
  lsof -tiTCP:"${LOCAL_PORT}" -sTCP:LISTEN | xargs -r kill >/dev/null 2>&1 || true
  echo "Stopped MR-RATE knowledge tunnel session '${TMUX_SESSION}'."
}

status_tunnel() {
  if ! port_listening; then
    echo "MR-RATE knowledge tunnel is not running."
    exit 1
  fi
  echo "MR-RATE knowledge tunnel is running on localhost:${LOCAL_PORT}."
  curl -fsS "${HEALTH_URL}"
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
  echo "MR-RATE knowledge tunnel is not running."
  exit 1
}

case "${ACTION}" in
  start) start_tunnel ;;
  stop) stop_tunnel ;;
  restart) stop_tunnel || true; start_tunnel ;;
  status) status_tunnel ;;
  logs) logs_tunnel ;;
  *)
    echo "Usage: $0 {start|stop|restart|status|logs}" >&2
    exit 1
    ;;
esac
