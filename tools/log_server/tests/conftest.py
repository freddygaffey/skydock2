"""Pytest path setup: repo root + ``tools/log_server`` on ``PYTHONPATH``."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_LOG_SERVER = _ROOT / "tools" / "log_server"

for _p in (_ROOT, _LOG_SERVER):
    s = str(_p)
    if s not in sys.path:
        sys.path.insert(0, s)
