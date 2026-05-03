#!/usr/bin/env bash
# Pi -> local mission sync: reliable, resumable, verified.
# Env: SKYDOCK_RPI_SSH (default fred@rpi.local), SKYDOCK_RPI_REMOTE_DIR (default ~/skydock2)
# Args:
#   optional mission IDs — only those missions, in listed order
#   --background  — detach with nohup (log: SYNC_RPI_LOG or repo/rpi_sync.log)
# If none: all remote missions — locally missing first, then hash check on existing.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
RPI_SSH="${SKYDOCK_RPI_SSH:-fred@rpi.local}"
REMOTE_ROOT="${SKYDOCK_RPI_REMOTE_DIR:-~/skydock2}"
LOCAL_MISSIONS_ROOT="${SKYDOCK_RPI_MISSIONS_DIR:-$REPO_ROOT/rpi_missions}"

SSH_OPTS=(
  -o ConnectTimeout=8
  -o BatchMode=yes
  -o StrictHostKeyChecking=no
  -o ServerAliveInterval=30
  -o ServerAliveCountMax=6
)

remote_hash_of_mission() {
  local mid="$1"
  ssh "${SSH_OPTS[@]}" "$RPI_SSH" bash -s -- "$mid" "$REMOTE_ROOT" <<'REMOTE_HASH'
set -euo pipefail
mid="$1"
REMOTE_ROOT="$2"
case "$REMOTE_ROOT" in ~|~/*) BASE="$HOME/${REMOTE_ROOT#~}";; *) BASE="$REMOTE_ROOT";; esac
cd "$BASE/missions"
[[ -d "$mid" ]]
python3 - <<'PY' "$mid"
import hashlib, os, sys
mid = sys.argv[1]
h = hashlib.sha256()
for root, dirs, files in os.walk(mid):
    dirs.sort()
    files.sort()
    for fn in files:
        p = os.path.join(root, fn)
        rel = os.path.relpath(p, mid).replace(os.sep, "/")
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        with open(p, "rb") as f:
            while True:
                b = f.read(1024 * 1024)
                if not b:
                    break
                h.update(b)
        h.update(b"\0")
print(h.hexdigest())
PY
REMOTE_HASH
}

remote_frame_count() {
  local mid="$1"
  ssh "${SSH_OPTS[@]}" "$RPI_SSH" bash -s -- "$mid" "$REMOTE_ROOT" <<'REMOTE_COUNT'
set -euo pipefail
mid="$1"
REMOTE_ROOT="$2"
case "$REMOTE_ROOT" in ~|~/*) BASE="$HOME/${REMOTE_ROOT#~}";; *) BASE="$REMOTE_ROOT";; esac
cd "$BASE/missions"
if [[ -d "$mid/frames" ]]; then
  find "$mid/frames" -type f \( -iname '*.jpg' -o -iname '*.jpeg' \) 2>/dev/null | wc -l | tr -d ' '
else
  echo 0
fi
REMOTE_COUNT
}

local_frame_count() {
  local mid="$1"
  local d="$LOCAL_MISSIONS_ROOT/$mid/frames"
  if [[ -d "$d" ]]; then
    find "$d" -type f \( -iname '*.jpg' -o -iname '*.jpeg' \) 2>/dev/null | wc -l | tr -d ' '
  else
    echo 0
  fi
}

local_hash_of_mission() {
  local mid="$1"
  local f="$LOCAL_MISSIONS_ROOT/$mid/manifest.txt"
  [[ -f "$f" ]] || return 1
  sed -n 's/^source_hash=//p' "$f" | head -n 1
}

restore_local_mission() {
  local mid="$1"
  local mdir="$LOCAL_MISSIONS_ROOT/$mid"
  local gz

  echo "    [restore] mission $mid"
  if [[ -f "$mdir/frames.tar" ]]; then
    echo "    [restore] extracting frames.tar"
    tar -xf "$mdir/frames.tar" -C "$mdir"
    rm -f "$mdir/frames.tar"
  fi

  shopt -s nullglob
  for gz in "$mdir"/*.gz; do
    echo "    [restore] gunzip $(basename "$gz")"
    gzip -dc "$gz" > "${gz%.gz}"
    rm -f "$gz"
  done
  shopt -u nullglob
}

sync_one_mission() {
  local mid="$1"
  echo "    [stream] receiving bundle for $mid"
  ssh "${SSH_OPTS[@]}" "$RPI_SSH" bash -s -- "$mid" "$REMOTE_ROOT" <<'REMOTE_STREAM' | tar -xf - -C "$LOCAL_MISSIONS_ROOT"
set -euo pipefail
mid="$1"
REMOTE_ROOT="$2"
case "$REMOTE_ROOT" in ~|~/*) BASE="$HOME/${REMOTE_ROOT#~}";; *) BASE="$REMOTE_ROOT";; esac
cd "$BASE/missions"
[[ -d "$mid" ]]

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/$mid"

hash="$(python3 - <<'PY' "$mid"
import hashlib, os, sys
mid = sys.argv[1]
h = hashlib.sha256()
for root, dirs, files in os.walk(mid):
    dirs.sort()
    files.sort()
    for fn in files:
        p = os.path.join(root, fn)
        rel = os.path.relpath(p, mid).replace(os.sep, "/")
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        with open(p, "rb") as f:
            while True:
                b = f.read(1024 * 1024)
                if not b:
                    break
                h.update(b)
        h.update(b"\0")
print(h.hexdigest())
PY
)"

if [[ -d "$mid/frames" ]]; then
  tar -cf "$tmp/$mid/frames.tar" -C "$mid" frames
fi

shopt -s nullglob
for jf in "$mid"/*.json "$mid"/*.jsonl; do
  [[ -f "$jf" ]] || continue
  gzip -c "$jf" > "$tmp/$mid/$(basename "$jf").gz"
done
shopt -u nullglob

{
  echo "mission_id=$mid"
  echo "source_hash=$hash"
} > "$tmp/$mid/manifest.txt"

tar -cf - -C "$tmp" "$mid"
REMOTE_STREAM
}

reorder_missing_first() {
  local -a missing have
  local mid
  missing=()
  have=()
  for mid in "${ALL_REMOTE[@]}"; do
    if [[ ! -d "$LOCAL_MISSIONS_ROOT/$mid" ]]; then
      missing+=("$mid")
    else
      have+=("$mid")
    fi
  done
  MISSION_IDS=("${missing[@]}" "${have[@]}")
  echo "Order: ${#missing[@]} missing locally first, then ${#have[@]} existing (hash check)"
  echo
}

main() {
  echo "=== sync_rpi_logs: Pi -> local ==="
  echo "SSH target     : $RPI_SSH"
  echo "Remote root    : $REMOTE_ROOT"
  echo "Local missions : $LOCAL_MISSIONS_ROOT"
  echo

  if ! ssh "${SSH_OPTS[@]}" "$RPI_SSH" exit >/dev/null 2>&1; then
    echo "ERROR: cannot reach $RPI_SSH" >&2
    exit 1
  fi

  mkdir -p "$LOCAL_MISSIONS_ROOT"

  mapfile -t ALL_REMOTE < <(
    ssh "${SSH_OPTS[@]}" "$RPI_SSH" bash -s -- "$REMOTE_ROOT" <<'LIST_REMOTE'
set -euo pipefail
REMOTE_ROOT="$1"
case "$REMOTE_ROOT" in ~|~/*) BASE="$HOME/${REMOTE_ROOT#~}";; *) BASE="$REMOTE_ROOT";; esac
cd "$BASE/missions"
ls -1d [0-9]* 2>/dev/null | sort || true
LIST_REMOTE
  )

  if [[ "${#ALL_REMOTE[@]}" -eq 0 ]]; then
    echo "No mission folders on Pi under missions/"
    exit 0
  fi

  if [[ "$#" -gt 0 ]]; then
    MISSION_IDS=("$@")
    start_idx=0
  else
    start_idx=0
    reorder_missing_first
  fi

  total=$((${#MISSION_IDS[@]} - start_idx))
  echo "Remote mission count : ${#ALL_REMOTE[@]}"
  echo "Missions this run    : $total"
  echo

  done_n=0
  skipped_n=0
  updated_n=0
  failed_n=0

  for ((i = start_idx; i < ${#MISSION_IDS[@]}; i++)); do
    mid="${MISSION_IDS[$i]}"
    done_n=$((done_n + 1))
    echo "[$done_n/$total] Mission $mid"

    if [[ ! -d "$LOCAL_MISSIONS_ROOT/$mid" ]]; then
      echo "    [missing locally] download (no hash pass needed)"
      rm -rf "$LOCAL_MISSIONS_ROOT/$mid"
    else
      echo "    [hash] remote"
      remote_hash="$(remote_hash_of_mission "$mid")"
      local_hash="$(local_hash_of_mission "$mid" || true)"

      if [[ -n "$local_hash" && "$local_hash" == "$remote_hash" ]]; then
        echo "    [skip] hash unchanged"
        skipped_n=$((skipped_n + 1))
        continue
      fi

      if [[ -n "$local_hash" ]]; then
        echo "    [sync] hash changed — replacing local"
        rm -rf "$LOCAL_MISSIONS_ROOT/$mid"
      else
        echo "    [sync] local incomplete — re-download"
        rm -rf "$LOCAL_MISSIONS_ROOT/$mid"
      fi
    fi

    if ! sync_one_mission "$mid"; then
      echo "    ERROR: stream/extract failed" >&2
      failed_n=$((failed_n + 1))
      continue
    fi

    if ! restore_local_mission "$mid"; then
      echo "    ERROR: restore failed" >&2
      failed_n=$((failed_n + 1))
      continue
    fi

    if [[ ! -f "$LOCAL_MISSIONS_ROOT/$mid/mission.jsonl" ]]; then
      echo "    ERROR: mission.jsonl missing after restore" >&2
      failed_n=$((failed_n + 1))
      continue
    fi

    echo "    [verify] frame counts"
    rcnt="$(remote_frame_count "$mid")"
    lcnt="$(local_frame_count "$mid")"
    if [[ "$rcnt" != "$lcnt" ]]; then
      echo "    ERROR: frame count mismatch remote=$rcnt local=$lcnt" >&2
      failed_n=$((failed_n + 1))
      continue
    fi

    echo "    OK — frames=$lcnt, mission.jsonl present"
    updated_n=$((updated_n + 1))
  done

  echo
  echo "=== summary ==="
  echo "Updated: $updated_n"
  echo "Skipped: $skipped_n"
  echo "Failed:  $failed_n"

  if [[ "$failed_n" -gt 0 ]]; then
    exit 1
  fi
}

if [[ "${1:-}" == "--background" ]]; then
  shift
  LOG="${SYNC_RPI_LOG:-$REPO_ROOT/rpi_sync.log}"
  touch "$LOG"
  nohup bash "$0" "$@" >>"$LOG" 2>&1 &
  echo "sync_rpi_logs: background PID $!  log: $LOG"
  exit 0
fi

main "$@"
