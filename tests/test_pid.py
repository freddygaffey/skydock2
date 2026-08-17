"""Unit tests for the dt-based Pid in states/shared_data.py.

Contract: get_v(error, time_ns, speedup) integrates error weighted by the
sim-time interval between detection timestamps. First sample, repeated stale
frames (dt == 0), and reacquisition gaps (dt > max_dt_s) contribute no I/D.
Ki is per-second: immune to FSM tick rate and model FPS.

Run with:  python -m pytest tests/test_pid.py
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from states.shared_data import Pid  # noqa: E402

NS = 1_000_000_000  # 1 second in ns


def test_first_sample_is_pure_p():
    pid = Pid(p=0.5, i=1.0, d=1.0)
    assert pid.get_v(2.0, 10 * NS, 1.0) == pytest.approx(1.0)  # 0.5*2, no I/D
    assert pid.i_sum == 0


def test_integral_weights_by_elapsed_seconds():
    pid = Pid(p=0.0, i=1.0, d=0.0)
    pid.get_v(3.0, 0, 1.0)
    out = pid.get_v(3.0, int(0.1 * NS), 1.0)   # 0.1 s later
    assert pid.i_sum == pytest.approx(0.3)      # 3.0 * 0.1
    assert out == pytest.approx(0.3)


def test_ki_is_rate_independent():
    # Same 1 s of steady error sampled at 10 Hz vs 30 Hz -> same integral.
    for hz in (10, 30):
        pid = Pid(p=0.0, i=1.0, d=0.0)
        for k in range(hz + 1):
            pid.get_v(2.0, int(k * NS / hz), 1.0)
        assert pid.i_sum == pytest.approx(2.0), hz


def test_repeated_stale_frame_integrates_nothing():
    pid = Pid(p=0.7, i=1.0, d=0.0)
    pid.get_v(1.0, 5 * NS, 1.0)
    before = pid.i_sum
    pid.get_v(1.0, 5 * NS, 1.0)                 # same timestamp: dt == 0
    assert pid.i_sum == before


def test_gap_larger_than_max_dt_is_skipped():
    pid = Pid(p=0.0, i=1.0, d=0.0)
    pid.get_v(1.0, 0, 1.0)
    pid.get_v(1.0, int(3 * NS), 1.0)            # 3 s blind gap > max_dt_s
    assert pid.i_sum == 0


def test_speedup_converts_wall_dt_to_sim_dt():
    # 0.05 s wall at 10x sim speed = 0.5 s of physics.
    pid = Pid(p=0.0, i=1.0, d=0.0)
    pid.get_v(1.0, 0, 10.0)
    pid.get_v(1.0, int(0.05 * NS), 10.0)
    assert pid.i_sum == pytest.approx(0.5)


def test_negative_error_drains_integral():
    pid = Pid(p=0.0, i=1.0, d=0.0)
    pid.get_v(2.0, 0, 1.0)
    pid.get_v(2.0, int(0.1 * NS), 1.0)          # +0.2
    pid.get_v(-2.0, int(0.2 * NS), 1.0)         # -0.2
    assert pid.i_sum == pytest.approx(0.0)


def test_output_clamped_to_max_v():
    pid = Pid(p=1.0, i=0.0, d=0.0)
    assert pid.get_v(50.0, 0, 1.0) == pid.max_v
    assert pid.get_v(-50.0, int(0.01 * NS), 1.0) == pid.min_v


def test_clear_history_resets_everything():
    pid = Pid()
    pid.get_v(1.0, 0, 1.0)
    pid.get_v(1.0, int(0.1 * NS), 1.0)
    pid.clear_history()
    assert pid.i_sum == 0
    assert pid.last_time_ns is None
    assert pid.last_distance_from_target is None
