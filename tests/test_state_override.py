"""Tests for states/override.py — the safe/manual state.

override() must always halt autonomous velocity commands and only release the
drone into SCAN/HOMING when the pilot has enabled autonomy in GUIDED mode.

Run with:  python -m pytest tests/test_state_override.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.support import FakeTelemetry  # noqa: E402
import states.override as override_mod  # noqa: E402
from states.enum import DroneStateEnum  # noqa: E402


def run_override(monkeypatch, drone_state, frame=None):
    tel = FakeTelemetry()
    monkeypatch.setattr(override_mod, "telemetry_singleton", tel)
    result = override_mod.override(drone_state, frame)
    return result, tel


def test_autonomy_disabled_stays_in_override(monkeypatch, make_drone_state):
    state = make_drone_state(mode="GUIDED", autonomy_enabled=False)
    result, tel = run_override(monkeypatch, state)
    assert result == DroneStateEnum.OVERRIDE
    assert tel.stop_calls >= 1


def test_rtl_mode_goes_to_rtl(monkeypatch, make_drone_state):
    state = make_drone_state(mode="RTL")
    result, _ = run_override(monkeypatch, state)
    assert result == DroneStateEnum.RTL


def test_non_guided_mode_stays_in_override(monkeypatch, make_drone_state):
    for mode in ("AUTO", "LOITER", "STABILIZE", "LAND"):
        state = make_drone_state(mode=mode)
        result, _ = run_override(monkeypatch, state)
        assert result == DroneStateEnum.OVERRIDE, mode


def test_force_homing_in_guided_goes_to_homing(monkeypatch, make_drone_state):
    state = make_drone_state(mode="GUIDED", force_homing=True)
    result, _ = run_override(monkeypatch, state)
    assert result == DroneStateEnum.HOMING


def test_autonomy_in_guided_goes_to_scan(monkeypatch, make_drone_state):
    state = make_drone_state(mode="GUIDED", autonomy_enabled=True)
    result, _ = run_override(monkeypatch, state)
    assert result == DroneStateEnum.SCAN


def test_velocity_always_stopped(monkeypatch, make_drone_state):
    # The very first thing override() does is halt any running velocity thread,
    # regardless of which branch it then takes.
    for kwargs in (dict(mode="GUIDED"), dict(mode="RTL"), dict(mode="AUTO"),
                   dict(mode="GUIDED", autonomy_enabled=False)):
        state = make_drone_state(**kwargs)
        _, tel = run_override(monkeypatch, state)
        assert tel.stop_calls >= 1, kwargs
