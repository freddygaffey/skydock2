"""Tests for the homing() state function in states/homing.py.

homing() keeps two timers in states/shared_data.py (last_det_time,
start_homing_time); the reset_state_globals fixture clears them around every
test, and timeout tests pre-set them relative to the real clock.

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
import states.shared_data as shared_data  # noqa: E402
from states.enum import DroneStateEnum  # noqa: E402
from constants import (  # noqa: E402
    MIN_ALT, MAX_HOMING_ALT, MAX_HOMING_TIME, TIME_WAIT_FOR_DET, MIN_SPRAY_ERROR, TARGET_SIM_SPEED,
)


def setup_homing(monkeypatch):
    tel = FakeTelemetry()
    monkeypatch.setattr(homing_mod, "telemetry_singleton", tel)
    monkeypatch.setattr(homing_mod, "log_event", MagicMock())
    return tel


def test_first_call_initialises_timers(monkeypatch, make_drone_state, make_frame,
                                       reset_state_globals):
    setup_homing(monkeypatch)
    assert shared_data.last_det_time is None
    assert shared_data.start_homing_time is None

    homing_mod.homing(make_drone_state(alt=10.0), make_frame())

    assert shared_data.last_det_time is not None
    assert shared_data.start_homing_time is not None


def test_total_timeout_gives_up_to_goto(monkeypatch, make_drone_state, make_frame,
                                        make_detection, reset_state_globals):
    tel = setup_homing(monkeypatch)
    now = time.time()
    shared_data.start_homing_time = now - (MAX_HOMING_TIME / TARGET_SIM_SPEED + 5)
    shared_data.last_det_time = now

    # Fires even with a perfectly good detection in frame.
    result = homing_mod.homing(make_drone_state(alt=10.0), make_frame(make_detection()))

    assert result == DroneStateEnum.GOTO
    assert tel.stop_calls == 1
    assert shared_data.start_homing_time is None  # timers reset for next session
    assert shared_data.last_det_time is None
    event = homing_mod.log_event.call_args_list[0][0][0]
    assert event == "homing_give_up_timeout"


def test_total_timeout_uses_measured_sim_speed(monkeypatch, make_drone_state, make_frame,
                                               make_detection, reset_state_globals):
    # Timeout must scale with the measured drone_state.sim_speed, not the
    # requested TARGET_SIM_SPEED: an elapsed time inside the nominal budget
    # fires once the measured speedup shrinks the wall-clock budget below it.
    tel = setup_homing(monkeypatch)
    now = time.time()
    elapsed = MAX_HOMING_TIME / (TARGET_SIM_SPEED * 2)
    shared_data.start_homing_time = now - elapsed
    shared_data.last_det_time = now

    state = make_drone_state(alt=10.0)
    state.sim_speed = TARGET_SIM_SPEED * 4  # budget becomes MAX/(4*TARGET) < elapsed
    result = homing_mod.homing(state, make_frame(make_detection()))

    assert result == DroneStateEnum.GOTO
    assert tel.stop_calls == 1
    event = homing_mod.log_event.call_args_list[0][0][0]
    assert event == "homing_give_up_timeout"


def test_no_detection_timeout_gives_up_to_goto(monkeypatch, make_drone_state, make_frame,
                                               reset_state_globals):
    tel = setup_homing(monkeypatch)
    now = time.time()
    shared_data.start_homing_time = now
    shared_data.last_det_time = now - (TIME_WAIT_FOR_DET / TARGET_SIM_SPEED + 5)

    result = homing_mod.homing(make_drone_state(alt=10.0), make_frame())  # empty frame

    assert result == DroneStateEnum.GOTO
    assert tel.stop_calls == 1
    assert shared_data.last_det_time is None
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
    assert shared_data.last_det_time is None       # session reset
    assert shared_data.start_homing_time is None
    event = homing_mod.log_event.call_args_list[0][0][0]
    assert event == "spray_ready"


def test_detection_refreshes_no_det_timer(monkeypatch, make_drone_state, make_frame,
                                          make_detection, reset_state_globals):
    # A detection arriving after a long blind stretch must reset the no-det
    # clock and keep homing (not give up to GOTO).
    setup_homing(monkeypatch)
    now = time.time()
    shared_data.start_homing_time = now
    shared_data.last_det_time = now - (TIME_WAIT_FOR_DET / TARGET_SIM_SPEED + 5)  # stale

    result = homing_mod.homing(make_drone_state(alt=10.0), make_frame(make_detection()))

    assert result == DroneStateEnum.HOMING
    assert shared_data.last_det_time is not None
    assert time.time() - shared_data.last_det_time < 1.0  # refreshed to "now"


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


def test_velocity_law_pid_with_cap(monkeypatch, make_drone_state, make_frame,
                                   make_detection, reset_state_globals):
    tel = setup_homing(monkeypatch)
    # Inject a known NED offset: vN/vE = clamp(p*e + i*sum(history) + d*de, ±max_v).
    monkeypatch.setattr(homing_mod, "detection_to_ned", lambda ds, det: (9.0, -1.0))
    monkeypatch.setattr(homing_mod, "detection_to_dist", lambda ds, det: math.hypot(9.0, 1.0))

    result = homing_mod.homing(make_drone_state(alt=10.0), make_frame(make_detection()))

    assert result == DroneStateEnum.HOMING
    n_pid, e_pid = shared_data.N_pid, shared_data.E_pid
    vN, vE, vD = tel.velocity_calls[0]
    assert vN == n_pid.max_v                                  # p*9 = 6.3, clamped
    assert vE == pytest_approx(-1.0 * e_pid.p + -1.0 * e_pid.i)  # linear regime
    assert vD == 0.3                                          # in-band altitude drifts down


def test_each_axis_uses_its_own_pid(monkeypatch, make_drone_state, make_frame,
                                    make_detection, reset_state_globals):
    # Regression guard: vN must come from N_pid(N) and vE from E_pid(E) —
    # sharing one instance mixes both axes' integrator history.
    tel = setup_homing(monkeypatch)
    monkeypatch.setattr(homing_mod, "detection_to_ned", lambda ds, det: (4.0, -9.0))
    monkeypatch.setattr(homing_mod, "detection_to_dist", lambda ds, det: math.hypot(4.0, 9.0))

    class StubPid:
        def __init__(self, out):
            self.out = out
            self.calls = []

        def get_v(self, error):
            self.calls.append(error)
            return self.out

        def clear_history(self):
            pass

    stub_n, stub_e = StubPid(0.11), StubPid(-0.22)
    monkeypatch.setattr(shared_data, "N_pid", stub_n)
    monkeypatch.setattr(shared_data, "E_pid", stub_e)

    homing_mod.homing(make_drone_state(alt=10.0), make_frame(make_detection()))

    assert stub_n.calls == [4.0]
    assert stub_e.calls == [-9.0]
    assert tel.velocity_calls[0][:2] == (0.11, -0.22)


def test_give_up_resets_pid_history(monkeypatch, make_drone_state, make_frame,
                                    make_detection, reset_state_globals):
    tel = setup_homing(monkeypatch)
    monkeypatch.setattr(homing_mod, "detection_to_ned", lambda ds, det: (1.0, 1.0))
    monkeypatch.setattr(homing_mod, "detection_to_dist", lambda ds, det: math.hypot(1.0, 1.0))

    # Accumulate integrator state over a couple of ticks.
    homing_mod.homing(make_drone_state(alt=10.0), make_frame(make_detection()))
    homing_mod.homing(make_drone_state(alt=10.0), make_frame(make_detection()))
    assert len(shared_data.N_pid.error_history) > 1

    # Force the total-timeout exit; the integrator must not leak into the next weed.
    shared_data.start_homing_time = time.time() - (MAX_HOMING_TIME / TARGET_SIM_SPEED + 5)
    result = homing_mod.homing(make_drone_state(alt=10.0), make_frame(make_detection()))

    assert result == DroneStateEnum.GOTO
    assert shared_data.N_pid.error_history == [0]
    assert shared_data.E_pid.error_history == [0]


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
