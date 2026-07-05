"""Tests for the homing() state function in states/homing.py.

homing() keeps two module-level globals (last_det_time, start_homing_time);
the reset_state_globals fixture clears them around every test, and timeout
tests pre-set them relative to the real clock.

Run with:  python -m pytest tests/test_state_homing.py
"""

import math
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.support import FakeTelemetry  # noqa: E402
import states.homing as homing_mod  # noqa: E402
from states.enum import DroneStateEnum  # noqa: E402
from constants import (  # noqa: E402
    MIN_ALT, MAX_HOMING_ALT, MAX_HOMING_TIME, TIME_WAIT_FOR_DET, MIN_SPRAY_ERROR, SIM_SPEED,
)


def setup_homing(monkeypatch):
    tel = FakeTelemetry()
    monkeypatch.setattr(homing_mod, "telemetry_singleton", tel)
    monkeypatch.setattr(homing_mod, "log_event", MagicMock())
    return tel


def test_first_call_initialises_timers(monkeypatch, make_drone_state, make_frame,
                                       reset_state_globals):
    setup_homing(monkeypatch)
    assert homing_mod.last_det_time is None
    assert homing_mod.start_homing_time is None

    homing_mod.homing(make_drone_state(alt=10.0), make_frame())

    assert homing_mod.last_det_time is not None
    assert homing_mod.start_homing_time is not None


def test_total_timeout_gives_up_to_goto(monkeypatch, make_drone_state, make_frame,
                                        make_detection, reset_state_globals):
    tel = setup_homing(monkeypatch)
    now = time.time()
    homing_mod.start_homing_time = now - (MAX_HOMING_TIME / SIM_SPEED + 5)
    homing_mod.last_det_time = now

    # Fires even with a perfectly good detection in frame.
    result = homing_mod.homing(make_drone_state(alt=10.0), make_frame(make_detection()))

    assert result == DroneStateEnum.GOTO
    assert tel.stop_calls == 1
    assert homing_mod.start_homing_time is None  # timers reset for next session
    assert homing_mod.last_det_time is None
    event = homing_mod.log_event.call_args_list[0][0][0]
    assert event == "homing_give_up_timeout"


def test_no_detection_timeout_gives_up_to_goto(monkeypatch, make_drone_state, make_frame,
                                               reset_state_globals):
    tel = setup_homing(monkeypatch)
    now = time.time()
    homing_mod.start_homing_time = now
    homing_mod.last_det_time = now - (TIME_WAIT_FOR_DET / SIM_SPEED + 5)

    result = homing_mod.homing(make_drone_state(alt=10.0), make_frame())  # empty frame

    assert result == DroneStateEnum.GOTO
    assert tel.stop_calls == 1
    assert homing_mod.last_det_time is None
    event = homing_mod.log_event.call_args_list[0][0][0]
    assert event == "homing_give_up_no_det"


def test_no_detection_climbs_to_search(monkeypatch, make_drone_state, make_frame,
                                       reset_state_globals):
    tel = setup_homing(monkeypatch)

    result = homing_mod.homing(make_drone_state(alt=10.0), make_frame())

    assert result == DroneStateEnum.HOMING
    assert tel.velocity_calls == [(0, 0, -0.4)]  # NED: negative down = climb


def test_no_detection_at_alt_cap_descends(monkeypatch, make_drone_state, make_frame,
                                          reset_state_globals):
    tel = setup_homing(monkeypatch)

    result = homing_mod.homing(make_drone_state(alt=MAX_HOMING_ALT + 1.0), make_frame())

    assert result == DroneStateEnum.HOMING
    assert tel.velocity_calls == [(0, 0, 0.5)]
    event = homing_mod.log_event.call_args_list[0][0][0]
    assert event == "homing_alt_cap"


def test_close_and_low_transitions_to_spray(monkeypatch, make_drone_state, make_frame,
                                            make_detection, reset_state_globals):
    tel = setup_homing(monkeypatch)
    # Centre detection => horizontal distance ~0; alt within MIN_ALT + 1 gate.
    state = make_drone_state(alt=MIN_ALT)

    result = homing_mod.homing(state, make_frame(make_detection()))

    assert result == DroneStateEnum.SPRAY
    assert tel.stop_calls == 1
    assert homing_mod.last_det_time is None       # session reset
    assert homing_mod.start_homing_time is None
    event = homing_mod.log_event.call_args_list[0][0][0]
    assert event == "spray_ready"


def test_detection_refreshes_no_det_timer(monkeypatch, make_drone_state, make_frame,
                                          make_detection, reset_state_globals):
    # A detection arriving after a long blind stretch must reset the no-det
    # clock and keep homing (not give up to GOTO).
    setup_homing(monkeypatch)
    now = time.time()
    homing_mod.start_homing_time = now
    homing_mod.last_det_time = now - (TIME_WAIT_FOR_DET / SIM_SPEED + 5)  # stale

    result = homing_mod.homing(make_drone_state(alt=10.0), make_frame(make_detection()))

    assert result == DroneStateEnum.HOMING
    assert homing_mod.last_det_time is not None
    assert time.time() - homing_mod.last_det_time < 1.0  # refreshed to "now"


def test_spray_gate_boundaries_are_inclusive(monkeypatch, make_drone_state, make_frame,
                                             make_detection, reset_state_globals):
    # dist == MIN_SPRAY_ERROR and alt == MIN_ALT + 1 are both still in-gate.
    tel = setup_homing(monkeypatch)
    monkeypatch.setattr(homing_mod, "detection_to_dist", lambda ds, det: MIN_SPRAY_ERROR)
    monkeypatch.setattr(homing_mod, "detection_to_ned", lambda ds, det: (0.0, 0.0))
    state = make_drone_state(alt=MIN_ALT + 1)

    result = homing_mod.homing(state, make_frame(make_detection()))

    assert result == DroneStateEnum.SPRAY
    assert tel.stop_calls == 1


def test_force_homing_blocks_spray_transition(monkeypatch, make_drone_state, make_frame,
                                              make_detection, reset_state_globals):
    setup_homing(monkeypatch)
    state = make_drone_state(alt=MIN_ALT, force_homing=True)

    result = homing_mod.homing(state, make_frame(make_detection()))

    assert result == DroneStateEnum.HOMING


def test_close_but_too_high_keeps_homing_and_descends(monkeypatch, make_drone_state,
                                                      make_frame, make_detection,
                                                      reset_state_globals):
    tel = setup_homing(monkeypatch)
    # Distance ~0 but alt above the MIN_ALT + 1 spray gate: falls through to
    # velocity control, which descends (vD = +0.3).
    state = make_drone_state(alt=MIN_ALT + 5.0)

    result = homing_mod.homing(state, make_frame(make_detection()))

    assert result == DroneStateEnum.HOMING
    assert len(tel.velocity_calls) == 1
    vN, vE, vD = tel.velocity_calls[0]
    assert abs(vN) < 0.1 and abs(vE) < 0.1
    assert vD == 0.3


def test_velocity_law_sqrt_with_cap(monkeypatch, make_drone_state, make_frame,
                                    make_detection, reset_state_globals):
    tel = setup_homing(monkeypatch)
    # Inject a known NED offset: vN = copysign(min(0.7*sqrt|N|, 2), N).
    monkeypatch.setattr(homing_mod, "detection_to_ned", lambda ds, det: (4.0, -9.0))
    monkeypatch.setattr(homing_mod, "detection_to_dist", lambda ds, det: math.hypot(4.0, 9.0))

    result = homing_mod.homing(make_drone_state(alt=10.0), make_frame(make_detection()))

    assert result == DroneStateEnum.HOMING
    vN, vE, vD = tel.velocity_calls[0]
    assert vN == pytest_approx(0.7 * 4.0 ** 0.5)   # 1.4, under the 2 m/s cap
    assert vE == -2.0                              # 0.7*sqrt(9)=2.1 capped at 2, sign kept
    assert vD == 0.3                               # in-band altitude drifts down


def test_below_min_alt_climbs_while_homing(monkeypatch, make_drone_state, make_frame,
                                           make_detection, reset_state_globals):
    tel = setup_homing(monkeypatch)
    monkeypatch.setattr(homing_mod, "detection_to_ned", lambda ds, det: (5.0, 0.0))
    monkeypatch.setattr(homing_mod, "detection_to_dist", lambda ds, det: 5.0)

    homing_mod.homing(make_drone_state(alt=MIN_ALT - 1.5), make_frame(make_detection()))

    assert tel.velocity_calls[0][2] == -0.3  # climb back above the floor


def test_nearest_detection_wins(monkeypatch, make_drone_state, make_frame,
                                make_detection, reset_state_globals):
    setup_homing(monkeypatch)
    near = make_detection(px=600.0, py=600.0)
    far = make_detection(px=100.0, py=100.0)
    dists = {id(near): 4.0, id(far): 20.0}
    chosen = []
    monkeypatch.setattr(homing_mod, "detection_to_dist", lambda ds, det: dists[id(det)])
    monkeypatch.setattr(homing_mod, "detection_to_ned",
                        lambda ds, det: chosen.append(det) or (1.0, 1.0))

    homing_mod.homing(make_drone_state(alt=10.0), make_frame(far, near))

    assert chosen == [near]


def pytest_approx(x, rel=1e-9):
    import pytest
    return pytest.approx(x, rel=rel)
