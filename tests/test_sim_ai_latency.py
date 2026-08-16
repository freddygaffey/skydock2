"""Tests for sim_ai.LatencyBuffer and the SIM_AI_LATENCY_MS constant.

The buffer delays frames by a fixed tick count (SIM_AI_LATENCY_MS sim-time
milliseconds at TARGET_FPS ticks per sim-second) so the FSM consumes
detections that are pipeline-latency old, like the real camera -> Hailo path.

Run with:  python -m pytest tests/test_sim_ai_latency.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import constants  # noqa: E402
from sim_ai import LatencyBuffer  # noqa: E402


def test_zero_latency_publishes_immediately():
    buf = LatencyBuffer(0)
    for tag in ("a", "b", "c"):
        assert buf.push(tag) == tag


def test_frames_delayed_by_exactly_n_ticks_in_order():
    buf = LatencyBuffer(3)
    frames = list(range(10))
    out = [buf.push(f) for f in frames]
    assert out[:3] == [None, None, None]
    assert out[3:] == frames[:7]


def test_negative_latency_clamped_to_zero():
    buf = LatencyBuffer(-2)
    assert buf.push("a") == "a"


def test_constant_maps_to_whole_tick_count():
    ticks = round(constants.SIM_AI_LATENCY_MS / 1000 * constants.TARGET_FPS)
    assert ticks >= 0
    buf = LatencyBuffer(ticks)
    assert buf.latency_frames == ticks
