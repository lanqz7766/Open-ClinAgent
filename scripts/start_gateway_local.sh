#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${CLINAGENT_LOCAL_PORT:-3000}"
BUILD_UI="${CLINAGENT_BUILD_UI:-auto}"
RUNNER=()
LOGO_SOURCE="frontend/public/clinagent-logo-mark.svg"
ANSI_RESET=$'\033[0m'
ANSI_BOLD=$'\033[1m'
ANSI_GOLD=$'\033[38;2;210;146;70m'
ANSI_GOLD_SOFT=$'\033[38;2;235;205;166m'
ANSI_MUTED=$'\033[38;2;142;125;102m'

supports_color() {
  [[ -t 1 ]] || return 1
  [[ "${TERM:-}" != "dumb" ]]
}

print_banner() {
  if ! supports_color; then
    cat <<EOF
ClinAgent
local gateway on http://127.0.0.1:${PORT}/demo
EOF
    return 0
  fi

  printf '\n'
  printf '%s' "${ANSI_GOLD}"
  printf '                     ▗▄▄▖\n'
  printf '                  ▗██████▖\n'
  printf '               ▗██████████▖\n'
  printf '             ▗██████  █████▖\n'
  printf '            ▐█████      ████▌\n'
  printf '             ▜████▖  ▗█████▛\n'
  printf '               ▜██████████▛\n'
  printf '                 ▜██████▛\n'
  printf '%s' "${ANSI_RESET}"
  printf '%s%sClinAgent%s %sGateway%s\n' "${ANSI_BOLD}" "${ANSI_GOLD}" "${ANSI_RESET}" "${ANSI_GOLD_SOFT}" "${ANSI_RESET}"
  printf '%slogo source:%s %s%s%s\n' "${ANSI_MUTED}" "${ANSI_RESET}" "${ANSI_GOLD_SOFT}" "${LOGO_SOURCE}" "${ANSI_RESET}"
  printf '%slocal gateway:%s %shttp://127.0.0.1:%s/demo%s\n' "${ANSI_MUTED}" "${ANSI_RESET}" "${ANSI_GOLD_SOFT}" "${PORT}" "${ANSI_RESET}"
  printf '\n'
}

pick_runner() {
  if [[ -x "${ROOT_DIR}/.venv/bin/clinagent" ]]; then
    RUNNER=("${ROOT_DIR}/.venv/bin/clinagent")
    return 0
  fi
  if command -v clinagent >/dev/null 2>&1; then
    RUNNER=("$(command -v clinagent)")
    return 0
  fi
  if [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
    RUNNER=("${ROOT_DIR}/.venv/bin/python" "-m" "clinagent")
    return 0
  fi
  RUNNER=("python3" "-m" "clinagent")
}

ui_build_needed() {
  local built_index="${ROOT_DIR}/src/clinagent/ui/demo-next/index.html"
  if [[ ! -f "${built_index}" ]]; then
    return 0
  fi
  if find "${ROOT_DIR}/frontend/src" "${ROOT_DIR}/frontend/public" -type f -newer "${built_index}" -print -quit | grep -q .; then
    return 0
  fi
  return 1
}

maybe_build_ui() {
  [[ -f "${ROOT_DIR}/frontend/package.json" ]] || return 0
  if [[ "${BUILD_UI}" == "0" || "${BUILD_UI}" == "false" ]]; then
    return 0
  fi
  if [[ "${BUILD_UI}" != "1" && "${BUILD_UI}" != "true" ]] && ! ui_build_needed; then
    return 0
  fi
  if ! command -v npm >/dev/null 2>&1; then
    echo "[clinagent] frontend build skipped: npm not found" >&2
    return 0
  fi
  echo "[clinagent] building frontend bundle"
  (cd "${ROOT_DIR}/frontend" && npm run build >/dev/null)
}

stop_existing_gateway() {
  local pid
  pid="$(lsof -tiTCP:${PORT} -sTCP:LISTEN 2>/dev/null | head -n 1 || true)"
  [[ -n "${pid}" ]] || return 0

  local command
  command="$(ps -o command= -p "${pid}" 2>/dev/null || true)"
  if [[ "${command}" == *"clinagent"* && "${command}" == *"--serve"* ]]; then
    echo "[clinagent] stopping existing gateway on port ${PORT} (pid ${pid})"
    kill "${pid}"
    for _ in {1..20}; do
      if ! kill -0 "${pid}" 2>/dev/null; then
        return 0
      fi
      sleep 0.2
    done
    echo "[clinagent] existing gateway on port ${PORT} did not stop cleanly" >&2
    exit 1
  fi

  echo "[clinagent] port ${PORT} is already in use by: ${command:-unknown process}" >&2
  echo "[clinagent] stop that process or choose another port with CLINAGENT_LOCAL_PORT" >&2
  exit 1
}

cd "${ROOT_DIR}"
pick_runner
stop_existing_gateway
maybe_build_ui

print_banner
echo "[clinagent] starting local gateway on http://127.0.0.1:${PORT}/demo"
echo "[clinagent] .env files are loaded by ClinAgent automatically; do not source them in the shell"

exec "${RUNNER[@]}" --serve --port "${PORT}"
