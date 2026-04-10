#!/usr/bin/env bash
# Pull real_missions + mission logs from the Raspberry Pi: tar over SSH, unpack locally
# (same as log server "Sync RPi"). Run from repo root: ./pull_logs_rpi.sh
set -euo pipefail
REPO="$(cd "$(dirname "$0")" && pwd)"
R="${SKYDOCK_RPI_SSH:-fred@rpi.local}"
REMOTE="${SKYDOCK_RPI_REMOTE_DIR-}"
if [[ -z "${REMOTE}" ]]; then
  REMOTE='~/skydock2'
fi
SSH_OPTS=(ssh -o ConnectTimeout=8 -o BatchMode=yes -o StrictHostKeyChecking=no)
mkdir -p "${REPO}/rpi_missions" "${REPO}/real_missions"

# Shell fragment for remote `cd` (~/... → $HOME/... on the Pi)
remote_cd() {
  local s="$1"
  case "$s" in
    ~/*) printf '"$HOME%s"' "${s:1}" ;;
    *) printf '%q' "$s" ;;
  esac
}
CD_REMOTE="$(remote_cd "${REMOTE}")"

"${SSH_OPTS[@]}" "${R}" "cd ${CD_REMOTE} && tar czf - real_missions" \
  | tar -xzf - -C "${REPO}/real_missions" --strip-components=1

"${SSH_OPTS[@]}" "${R}" "cd ${CD_REMOTE} && tar czf - missions" \
  | tar -xzf - -C "${REPO}/rpi_missions" --strip-components=1
