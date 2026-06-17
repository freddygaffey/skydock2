"""Tests for the StateMachine dispatch/guard logic in fsm.py.

State functions themselves are tested in tests/test_state_*.py; here they are
replaced with mocks so only the machine's wiring is under test: the
telemetry-ready gate, the RTL/override safety guard that runs before every
state, the loop-stop contract (update() -> False on RTL/DONE), and
transition/tick logging.

Run with:  python -m pytest tests/test_fsm_machine.py
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.support import FakeTelemetry  # noqa: E402
import fsm as fsm_mod  # noqa: E402
from fsm import StateMachine  # noqa: E402
from states.enum import DroneStateEnum  # noqa: E402

STATE_FN_NAMES = ("override", "scan", "goto", "homing", "spraying", "rtl")


def setup_machine(monkeypatch, drone_state, frame=None, start=DroneStateEnum.OVERRIDE):
    """StateMachine with mocked collaborators; each state fn echoes its own state."""
    tel = FakeTelemetry(drone_state=drone_state)
    monkeypatch.setattr(fsm_mod, "telemetry_singleton", tel)
    monkeypatch.setattr(fsm_mod, "ai_storage_singleton",
                        SimpleNamespace(get_latest_frame=lambda: frame))
    monkeypatch.setattr(fsm_mod, "log_event", MagicMock())
    echoes = {
        "override": DroneStateEnum.OVERRIDE,
        "scan": DroneStateEnum.SCAN,
        "goto": DroneStateEnum.GOTO,
        "homing": DroneStateEnum.HOMING,
        "spraying": DroneStateEnum.SPRAY,
        "rtl": DroneStateEnum.RTL,
    }
    mocks = {}
    for name in STATE_FN_NAMES:
        mocks[name] = MagicMock(return_value=echoes[name])
        monkeypatch.setattr(fsm_mod, name, mocks[name])
    sm = StateMachine()
    sm.current_state = start
    return sm, mocks


def test_update_waits_until_telemetry_ready(monkeypatch, make_drone_state):
    state = make_drone_state(ready=False)
    sm, mocks = setup_machine(monkeypatch, state)

    assert sm.update() is None
    assert sm.current_state == DroneStateEnum.OVERRIDE
    for m in mocks.values():
        m.assert_not_called()
    fsm_mod.log_event.assert_not_called()


@pytest.mark.parametrize("mode,expected", [
    ("RTL", DroneStateEnum.RTL),
    ("AUTO", DroneStateEnum.OVERRIDE),
    ("LOITER", DroneStateEnum.OVERRIDE),
    ("STABILIZE", DroneStateEnum.OVERRIDE),
    ("GUIDED", None),
])
def test_override_and_rtl_guard(monkeypatch, make_drone_state, mode, expected):
    sm, _ = setup_machine(monkeypatch, make_drone_state(mode=mode))
    assert sm._override_and_rtl_checks(make_drone_state(mode=mode)) == expected


@pytest.mark.parametrize("start", [
    DroneStateEnum.OVERRIDE, DroneStateEnum.SCAN, DroneStateEnum.GOTO,
    DroneStateEnum.HOMING, DroneStateEnum.SPRAY,
])
def test_pilot_rtl_pre_empts_every_state(monkeypatch, make_drone_state, start):
    state = make_drone_state(mode="RTL")
    sm, mocks = setup_machine(monkeypatch, state, start=start)

    sm.update()

    assert sm.current_state == DroneStateEnum.RTL
    for m in mocks.values():
        m.assert_not_called()  # guard short-circuits before any state fn


@pytest.mark.parametrize("start", [
    DroneStateEnum.SCAN, DroneStateEnum.GOTO,
    DroneStateEnum.HOMING, DroneStateEnum.SPRAY,
])
def test_leaving_guided_mode_forces_override(monkeypatch, make_drone_state, start):
    state = make_drone_state(mode="LOITER")
    sm, mocks = setup_machine(monkeypatch, state, start=start)

    sm.update()

    assert sm.current_state == DroneStateEnum.OVERRIDE
    for m in mocks.values():
        m.assert_not_called()


def test_guided_dispatches_to_state_function(monkeypatch, make_drone_state, make_frame):
    state = make_drone_state(mode="GUIDED")
    frame = make_frame()
    sm, mocks = setup_machine(monkeypatch, state, frame=frame, start=DroneStateEnum.SCAN)

    result = sm.update()

    assert result is None  # loop continues
    mocks["scan"].assert_called_once()
    assert sm.current_state == DroneStateEnum.SCAN


def test_rtl_state_stops_the_loop(monkeypatch, make_drone_state):
    # Pilot RTL: the guard returns RTL before rtl() runs, and the RTL case
    # unconditionally returns False to stop the mission loop.
    state = make_drone_state(mode="RTL")
    sm, mocks = setup_machine(monkeypatch, state, start=DroneStateEnum.RTL)

    assert sm.update() is False
    mocks["rtl"].assert_not_called()
    assert sm.current_state == DroneStateEnum.RTL


def test_rtl_in_guided_runs_rtl_and_stops_without_systemexit(monkeypatch, make_drone_state):
    # Mission-complete path: goto() returned RTL while still in GUIDED, so the
    # guard passes and rtl() runs. Pre-F1 this raised SystemExit; now it returns
    # DONE and the loop stops via the RTL case's return False.
    state = make_drone_state(mode="GUIDED")
    sm, mocks = setup_machine(monkeypatch, state, start=DroneStateEnum.RTL)
    mocks["rtl"].return_value = DroneStateEnum.DONE

    result = sm.update()  # must not raise SystemExit

    assert result is False
    mocks["rtl"].assert_called_once()
    assert sm.current_state == DroneStateEnum.DONE


def test_done_state_stops_the_loop(monkeypatch, make_drone_state):
    sm, _ = setup_machine(monkeypatch, make_drone_state(), start=DroneStateEnum.DONE)
    assert sm.update() is False
    assert sm.current_state == DroneStateEnum.DONE


def test_transition_is_logged_as_fsm_transition(monkeypatch, make_drone_state, make_frame):
    state = make_drone_state(mode="GUIDED")
    sm, mocks = setup_machine(monkeypatch, state, frame=make_frame(),
                              start=DroneStateEnum.SCAN)
    mocks["scan"].return_value = DroneStateEnum.GOTO

    sm.update()

    event = fsm_mod.log_event.call_args[0][0]
    kwargs = fsm_mod.log_event.call_args[1]
    assert event == "fsm_transition"
    assert kwargs["state_from"] == str(DroneStateEnum.SCAN)
    assert kwargs["state_to"] == str(DroneStateEnum.GOTO)


def test_same_state_is_logged_as_fsm_tick(monkeypatch, make_drone_state, make_frame):
    state = make_drone_state(mode="GUIDED")
    sm, _ = setup_machine(monkeypatch, state, frame=make_frame(),
                          start=DroneStateEnum.SCAN)

    sm.update()

    event = fsm_mod.log_event.call_args[0][0]
    assert event == "fsm_tick"
    assert fsm_mod.log_event.call_args[1]["state"] == str(DroneStateEnum.SCAN)
