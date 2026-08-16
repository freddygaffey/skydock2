"""Tests for DroneStateForHoming.update_sim_speedup / .sim_speed.

sim_speed is the measured FC-clock/wall-clock speedup ratio, EMA-updated from
(time.time_ns(), SYSTEM_TIME.time_boot_ms) pairs in wall_sim_time. It is
seeded with constants.TARGET_SIM_SPEED (the requested speedup).

Run with:  python -m pytest tests/test_sim_speed.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from constants import TARGET_SIM_SPEED  # noqa: E402
from drone_state import DroneStateForHoming  # noqa: E402


def feed(state, pairs):
    """Mimic the SYSTEM_TIME branch of set_pass_message for fabricated samples."""
    for wall_ns, fc_ms in pairs:
        state.wall_sim_time.append([wall_ns, fc_ms])
        state.update_sim_speedup()


def test_seeded_with_target_sim_speed():
    assert DroneStateForHoming().sim_speed == TARGET_SIM_SPEED


def test_single_sample_does_not_crash_or_change():
    state = DroneStateForHoming()
    feed(state, [(1_000_000_000, 500)])
    assert state.sim_speed == TARGET_SIM_SPEED


def test_same_wall_millisecond_does_not_crash():
    state = DroneStateForHoming()
    feed(state, [(1_000_000_000, 500), (1_000_000_100, 500)])  # 100 ns apart
    assert state.sim_speed == TARGET_SIM_SPEED


def test_converges_to_actual_ratio():
    state = DroneStateForHoming()
    # FC clock advances 1000 ms per 100 ms of wall clock => actual speedup 10.
    feed(state, [(i * 100_000_000, i * 1000) for i in range(30)])
    assert abs(state.sim_speed - 10.0) < 1e-3


def test_real_hardware_ratio_stays_near_one():
    state = DroneStateForHoming()
    state.sim_speed = 1.0
    # FC clock advances 200 ms per 200 ms wall => ratio 1 (real hardware).
    feed(state, [(i * 200_000_000, i * 200) for i in range(30)])
    assert abs(state.sim_speed - 1.0) < 1e-6


def test_tracks_change_in_actual_speedup():
    state = DroneStateForHoming()
    # Start at 10x, then the machine bogs down to 5x; the deque window plus the
    # EMA must move the estimate down toward 5.
    pairs = [(i * 100_000_000, i * 1000) for i in range(100)]
    last_wall, last_fc = pairs[-1]
    pairs += [(last_wall + i * 100_000_000, last_fc + i * 500) for i in range(1, 200)]
    feed(state, pairs)
    assert abs(state.sim_speed - 5.0) < 0.1


def test_message_path_populates_wall_sim_time():
    class FakeSystemTime:
        _type = "SYSTEM_TIME"
        time_boot_ms = 12345

    state = DroneStateForHoming()
    state.set_pass_message(FakeSystemTime())
    assert len(state.wall_sim_time) == 1
    assert state.wall_sim_time[0][1] == 12345
