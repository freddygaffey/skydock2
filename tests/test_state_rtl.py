"""Tests for states/rtl.py (locks safe-fix F1: bare exit() -> return DONE).

Run with:  python -m pytest tests/test_state_rtl.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from states.rtl import rtl  # noqa: E402
from states.enum import DroneStateEnum  # noqa: E402


def test_rtl_returns_done_without_exiting(make_drone_state, make_frame):
    # Must NOT raise SystemExit (the pre-fix behaviour killed the process).
    result = rtl(make_drone_state(), make_frame())
    assert result == DroneStateEnum.DONE
