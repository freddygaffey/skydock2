#!/usr/bin/env bash
# Pull real_missions + mission logs from the Raspberry Pi.
# Missions are pulled newest-first so results appear quickly.
# Usage: ./pull_logs_rpi.sh [last N missions, default all]
set -euo pipefail
REPO="$(cd "$(dirname "$0")" && pwd)"
R="${SKYDOCK_RPI_SSH:-fred@rpi.local}"
REMOTE="${SKYDOCK_RPI_REMOTE_DIR:-~/skydock2}"
LAST_N="${1:-}"
SSH="ssh -o ConnectTimeout=8 -o BatchMode=yes -o StrictHostKeyChecking=no"

log() { echo "[$(date +%H:%M:%S)] $*"; }

if [[ -n "${LAST_N}" && ! "${LAST_N}" =~ ^[0-9]+$ ]]; then
  echo "Usage: $0 [last N missions]  (e.g. $0 5)"
  exit 1
fi

log "remote host: ${R}"
log "remote dir:  ${REMOTE}"

mkdir -p "${REPO}/rpi_missions" "${REPO}/real_missions"

log "testing ssh connection (8s timeout)..."
if ! $SSH "${R}" true; then
  log "ERROR: cannot ssh to ${R}."
  log "  - is the Pi on and reachable?  try: ping rpi.local"
  log "  - BatchMode is on, so a password prompt = failure; ssh keys must be set up"
  log "  - override host with: SKYDOCK_RPI_SSH=fred@<ip> $0"
  exit 1
fi
log "ssh OK"

# real_missions — just JSON, compress it
log "=== real_missions ==="
rsync -avz --progress -e "${SSH}" "${R}:${REMOTE}/real_missions/" "${REPO}/real_missions/"

# Get mission dirs sorted newest-first
log "listing remote mission dirs..."
DIRS=$($SSH "${R}" "ls -1d ${REMOTE}/missions/[0-9]* 2>/dev/null | sort -r")
log "remote has $(echo "${DIRS}" | grep -c . || true) mission dirs"

if [[ -n "${LAST_N}" ]]; then
  DIRS=$(echo "${DIRS}" | head -n "${LAST_N}")
fi

TOTAL=$(echo "${DIRS}" | grep -c . || true)
log "=== missions: pulling ${TOTAL} dirs newest-first ==="
I=0
for dir in ${DIRS}; do
  name="$(basename "${dir}")"
  dest="${REPO}/rpi_missions/${name}"
  if [[ -f "${dest}/mission.jsonl" ]]; then
    log "[${I}/${TOTAL}] ${name} already exists, skipping"
  else
    size=$($SSH "${R}" "du -sh ${REMOTE}/missions/${name} 2>/dev/null | cut -f1" || echo "?")
    log "[${I}/${TOTAL}] pulling ${name} (${size}) ..."
    mkdir -p "${dest}"
    # No -z: JPEGs are already compressed. -v on the extract side shows each file.
    $SSH "${R}" "tar cf - -C ${REMOTE}/missions ${name}" \
      | tar -xvf - -C "${REPO}/rpi_missions"
    log "[${I}/${TOTAL}] ${name} done"
  fi
  I=$((I + 1))
done
log "Done."
