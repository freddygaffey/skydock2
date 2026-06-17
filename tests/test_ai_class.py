"""Tests for ai_class.py — Detection, Frame, and the _AiStorage singleton.

Run with:  python -m pytest tests/test_ai_class.py
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_class import Detection, Frame, _AiStorage, ai_storage_singleton  # noqa: E402


def test_get_center():
    det = Detection(label="ball", confidence=0.9, bbox=[(10.0, 20.0), (30.0, 60.0)])
    assert det.get_center() == (20.0, 40.0)


def test_to_db_format_shape():
    det = Detection(label="ball", confidence=0.5, bbox=[(0.0, 0.0), (4.0, 8.0)],
                    track_id=3, time_ns=123)
    row = det.to_db_format()
    assert row[0] == "ball"
    assert row[6:8] == (2.0, 4.0)   # centre
    assert row[8] == 3              # track_id
    assert row[9] == 123            # time_ns


@pytest.mark.parametrize("label,kept", [
    ("sports ball", True),
    ("sports_ball", True),
    ("Sports Ball", True),
    ("frisbee", True),
    ("person", False),
    ("car", False),
    ("", False),
])
def test_add_detection_label_filter(label, kept):
    frame = Frame([])
    det = Detection(label=label, confidence=0.9, bbox=[(0, 0), (10, 10)])
    frame.add_detection(det)
    assert (len(frame.detection) == 1) == kept


def test_ai_storage_is_singleton():
    assert _AiStorage() is _AiStorage()
    assert _AiStorage() is ai_storage_singleton


def test_set_and_get_latest_frame(reset_state_globals):
    det = Detection(label="sports ball", confidence=0.9, bbox=[(0, 0), (10, 10)])
    frame = Frame([det])
    ai_storage_singleton.set_latest_frame(frame)
    assert ai_storage_singleton.get_latest_frame() is frame


def test_start_sim_ai_noop_when_already_running(reset_state_globals):
    ai_storage_singleton.is_ai_running = True
    # Should early-return without importing sim_ai / spawning a thread.
    ai_storage_singleton.start_sim_ai([[1.0, 2.0]])
    assert ai_storage_singleton.is_ai_running is True
