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

if [[ -n "${LAST_N}" && ! "${LAST_N}" =~ ^[0-9]+$ ]]; then
  echo "Usage: $0 [last N missions]  (e.g. $0 5)"
  exit 1
fi

mkdir -p "${REPO}/rpi_missions" "${REPO}/real_missions"

# real_missions — just JSON, compress it
echo "=== real_missions ==="
rsync -avz "${R}:${REMOTE}/real_missions/" "${REPO}/real_missions/"

# Get mission dirs sorted newest-first
DIRS=$($SSH "${R}" "ls -1d ${REMOTE}/missions/[0-9]* 2>/dev/null | sort -r")

if [[ -n "${LAST_N}" ]]; then
  DIRS=$(echo "${DIRS}" | head -n "${LAST_N}")
fi

TOTAL=$(echo "${DIRS}" | grep -c . || true)
echo "=== missions: pulling ${TOTAL} dirs newest-first ==="
I=0
for dir in ${DIRS}; do
  name="$(basename "${dir}")"
  dest="${REPO}/rpi_missions/${name}"
  if [[ -f "${dest}/mission.jsonl" ]]; then
    echo "[${I}/${TOTAL}] ${name} already exists, skipping"
  else
    echo "[${I}/${TOTAL}] pulling ${name} ..."
    mkdir -p "${dest}"
    # No -z: JPEGs are already compressed
    $SSH "${R}" "tar cf - -C ${REMOTE}/missions ${name}" \
      | tar -xf - -C "${REPO}/rpi_missions"
  fi
  I=$((I + 1))
done
echo "Done."
