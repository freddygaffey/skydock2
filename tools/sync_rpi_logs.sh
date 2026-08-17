#!/usr/bin/env bash
# Pi -> local mission sync (rsync).
# Env: SKYDOCK_RPI_SSH (default fred@rpi.local), SKYDOCK_RPI_REMOTE_DIR (default ~/skydock2)
# Args: optional mission IDs (else: all). --background detaches.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
RPI_SSH="${SKYDOCK_RPI_SSH:-fred@rpi.local}"
REMOTE_ROOT="${SKYDOCK_RPI_REMOTE_DIR:-~/skydock2}"
LOCAL="${SKYDOCK_RPI_MISSIONS_DIR:-$REPO_ROOT/rpi_missions}"
SSH_OPTS="-o ConnectTimeout=8 -o BatchMode=yes -o StrictHostKeyChecking=no -o ServerAliveInterval=30"

if [[ "${1:-}" == "--background" ]]; then
  shift
  LOG="${SYNC_RPI_LOG:-$REPO_ROOT/rpi_sync.log}"
  nohup bash "$0" "$@" >>"$LOG" 2>&1 &
  echo "background PID $!  log: $LOG"
  exit 0
fi

mkdir -p "$LOCAL"

if [[ "$#" -gt 0 ]]; then
  MIDS=("$@")
else
  # macOS ships bash 3.2: no mapfile/readarray — stay 3.2-portable here.
  MIDS=()
  while IFS= read -r mid; do
    [ -n "$mid" ] && MIDS+=("$mid")
  done < <(ssh $SSH_OPTS "$RPI_SSH" "ls -1d $REMOTE_ROOT/missions/[0-9]* 2>/dev/null | xargs -n1 basename | sort -r")
fi

# bash 3.2 + set -u: expanding an empty array is an error — bail out first.
if [ "${#MIDS[@]}" -eq 0 ]; then
  echo "no missions found on $RPI_SSH"
  exit 0
fi

for mid in "${MIDS[@]}"; do
  echo "--- $mid ---"
  # small files: append mode for growing mission.jsonl.
  # macOS system rsync is 2.6.9-era: no --append-verify, no '***' filters —
  # keep to options in its usage list.
  rsync -aH --partial --inplace --append \
    --include='*.jsonl' --include='*.json' --include='manifest.txt' \
    --exclude='frames' --exclude='*' \
    -e "ssh $SSH_OPTS" \
    "$RPI_SSH:$REMOTE_ROOT/missions/$mid/" "$LOCAL/$mid/"
  # frames: whole-file, skip unchanged by size+mtime
  rsync -aH --partial -e "ssh $SSH_OPTS" \
    "$RPI_SSH:$REMOTE_ROOT/missions/$mid/frames/" "$LOCAL/$mid/frames/" 2>/dev/null || true
done
