"""Skydock mission log viewer (Flask).

Run without setting PYTHONPATH::

    python tools/log_server/app.py

(from repo root), or::

    cd tools/log_server && python app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_LOG_SERVER_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _LOG_SERVER_DIR.parent.parent


def _ensure_skydock_paths() -> None:
    """Repo root (for ``ai_class``, ``utils``) + this dir (for ``factory``, ``services``)."""
    for p in (_REPO_ROOT, _LOG_SERVER_DIR):
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)


_ensure_skydock_paths()

import os

from factory import create_app

app = create_app()


def _env_truth(name: str) -> bool:
    v = (os.environ.get(name) or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _env_falsy(name: str) -> bool:
    v = (os.environ.get(name) or "").strip().lower()
    return v in ("0", "false", "no", "off")


def _debug_mode_for_dev_server() -> bool:
    """True → Flask debug + auto-reload on code changes.

    Default **on** when running ``python app.py`` (local dev). Disable with
    ``LOG_SERVER_DEBUG=0`` or ``FLASK_DEBUG=0``. Enable explicitly with
    ``LOG_SERVER_DEBUG=1`` / ``FLASK_DEBUG=1`` (same as default when unset).
    """
    if _env_falsy("LOG_SERVER_DEBUG") or _env_falsy("FLASK_DEBUG"):
        return False
    ld = (os.environ.get("LOG_SERVER_DEBUG") or "").strip()
    fd = (os.environ.get("FLASK_DEBUG") or "").strip()
    if ld or fd:
        return _env_truth("LOG_SERVER_DEBUG") or _env_truth("FLASK_DEBUG")
    return True


if __name__ == "__main__":
    from config import data_paths

    # Default 5050: macOS uses 5000 for the AirPlay Receiver. Override with PORT=.
    port = int(os.environ.get("PORT", "5050"))
    _sim, missions_root = data_paths()
    missions = sorted(missions_root.glob("*/mission.jsonl")) if missions_root.exists() else []
    print(f"\n  MISSIONS_ROOT : {missions_root}  ({'exists' if missions_root.exists() else 'MISSING'})")
    print(f"  SIM_DATA_ROOT : {_sim}  ({'exists' if _sim.exists() else 'missing'})")
    if missions:
        print("  Mission files :")
        for m in missions:
            size_kb = m.stat().st_size // 1024
            print(f"    {m}  ({size_kb} KB)")
    else:
        print("  Mission files : (none found)")
    print()
    # threaded=True: parallel API requests (map + summary + frame_events) on first dashboard load
    debug = _debug_mode_for_dev_server()
    if debug:
        print("  Dev: debug + auto-reload on code changes (set LOG_SERVER_DEBUG=0 to disable).\n")
    app.run(host="0.0.0.0", port=port, debug=debug, use_reloader=debug, threaded=True)
