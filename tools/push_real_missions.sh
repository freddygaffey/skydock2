#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SRC_DIR="$PROJECT_DIR/real_missions"
DEST_DIR="~/skydock2/real_missions"
USER="fred"
PRIMARY_HOST="rpi.local"
FALLBACK_HOST="10.0.0.1"

SSH_OPTS="-o ConnectTimeout=5 -o BatchMode=yes"

# Resolve host
if ssh $SSH_OPTS "$USER@$PRIMARY_HOST" exit 2>/dev/null; then
    HOST="$PRIMARY_HOST"
elif ssh $SSH_OPTS "$USER@$FALLBACK_HOST" exit 2>/dev/null; then
    HOST="$FALLBACK_HOST"
else
    echo "Error: cannot reach $PRIMARY_HOST or $FALLBACK_HOST" >&2
    exit 1
fi
echo "Using host: $HOST"

# Collect matching files
FILES=("$SRC_DIR"/_*)
if [[ ! -e "${FILES[0]}" ]]; then
    echo "No files matching real_missions/_* found."
    exit 0
fi

# SCP each file
for f in "${FILES[@]}"; do
    echo "Copying $(basename "$f")..."
    scp $SSH_OPTS "$f" "$USER@$HOST:$DEST_DIR"
done
echo "Done."
