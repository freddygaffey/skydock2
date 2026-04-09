#!/usr/bin/env bash
set -euo pipefail

# Run the mission dashboard as a low-priority process on Linux/Raspberry Pi.
# Usage:
#   tools/log_server/run_low_priority.sh
#   PORT=5050 tools/log_server/run_low_priority.sh
#   NICE_LEVEL=15 IONICE_CLASS=3 tools/log_server/run_low_priority.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

PORT="${PORT:-5000}"
NICE_LEVEL="${NICE_LEVEL:-10}"      # 0..19 (higher = lower CPU priority)
IONICE_CLASS="${IONICE_CLASS:-3}"   # 3 = idle I/O class (best for background)
IONICE_LEVEL="${IONICE_LEVEL:-7}"   # used for class 2 only

cd "${REPO_ROOT}"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "Error: ${PYTHON_BIN} not found in PATH."
  exit 1
fi

echo "Starting log server in low-priority mode:"
echo "  PORT=${PORT}"
echo "  nice=${NICE_LEVEL}"
echo "  ionice class=${IONICE_CLASS} level=${IONICE_LEVEL}"
echo

BASE_CMD=("${PYTHON_BIN}" "tools/log_server/app.py")

if command -v ionice >/dev/null 2>&1; then
  if [[ "${IONICE_CLASS}" == "2" ]]; then
    # Best-effort class allows level 0..7.
    exec ionice -c 2 -n "${IONICE_LEVEL}" nice -n "${NICE_LEVEL}" env PORT="${PORT}" "${BASE_CMD[@]}"
  else
    # Idle class ignores level; runs only when disk is otherwise idle.
    exec ionice -c "${IONICE_CLASS}" nice -n "${NICE_LEVEL}" env PORT="${PORT}" "${BASE_CMD[@]}"
  fi
else
  echo "Warning: ionice not found; using nice only."
  exec nice -n "${NICE_LEVEL}" env PORT="${PORT}" "${BASE_CMD[@]}"
fi
