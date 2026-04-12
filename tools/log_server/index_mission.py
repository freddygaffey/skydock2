#!/usr/bin/env python3
"""Build or refresh ``mission_index.sqlite`` next to a ``mission.jsonl`` file.

Usage (from repo root, no PYTHONPATH needed)::

    python tools/log_server/index_mission.py missions/0001/mission.jsonl
    python tools/log_server/index_mission.py --mission-id 0001
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_LOG_SERVER_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _LOG_SERVER_DIR.parent.parent

for _p in (_REPO_ROOT, _LOG_SERVER_DIR):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)


def main() -> int:
    os.chdir(_LOG_SERVER_DIR)

    from config import data_paths
    from services.mission_index import build_mission_index, default_index_path
    from services.mission_store import resolve_mission_log

    ap = argparse.ArgumentParser(description="Build Skydock mission.jsonl SQLite index (sidecar).")
    ap.add_argument(
        "log_path",
        nargs="?",
        help="Path to mission.jsonl",
    )
    ap.add_argument("--mission-id", "-m", help="Mission id under MISSIONS_ROOT (sim missions root)")
    ap.add_argument("--rpi", action="store_true", help="Use RPi missions root (SKYDOCK_RPI_MISSIONS_DIR)")
    ap.add_argument("--force", "-f", action="store_true", help="Rebuild even if index looks current")
    args = ap.parse_args()

    log_path: Path | None = None
    if args.log_path:
        log_path = Path(args.log_path).expanduser().resolve()
    elif args.mission_id:
        _sim, missions_root = data_paths()
        if args.rpi:
            from config import rpi_missions_root

            missions_root = rpi_missions_root()
        p = resolve_mission_log(missions_root, str(args.mission_id))
        if p is None:
            print(f"No mission log for id {args.mission_id!r} under {missions_root}", file=sys.stderr)
            return 1
        log_path = p
    else:
        ap.error("Provide log_path or --mission-id")

    assert log_path is not None
    if not log_path.is_file():
        print(f"Not a file: {log_path}", file=sys.stderr)
        return 1

    out = build_mission_index(log_path, force=args.force)
    print(out)
    print(f"OK: {default_index_path(log_path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
