"""Tests for the spraying() state function in states/spray.py.

Run with:  python -m pytest tests/test_state_spray.py
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.support import FakeDB  # noqa: E402
import states.spray as spray_mod  # noqa: E402
from states.enum import DroneStateEnum  # noqa: E402
from constants import MIN_SPRAY_ERROR  # noqa: E402


def setup_spray(monkeypatch, closest_weed=None, ned=(0.0, 0.0)):
    db = FakeDB()
    db.closest_weed = closest_weed
    monkeypatch.setattr(spray_mod, "db_abstraction", db)
    monkeypatch.setattr(spray_mod, "log_event", MagicMock())
    monkeypatch.setattr(spray_mod, "detection_to_ned", lambda ds, det: ned)
    return db


def weed(weed_id=1):
    return SimpleNamespace(id=weed_id, lat=-35.3632, lon=149.1652)


def logged_events():
    return [c[0][0] for c in spray_mod.log_event.call_args_list]


def test_no_weeds_left_returns_rtl(monkeypatch, make_drone_state, make_frame,
                                   reset_state_globals):
    setup_spray(monkeypatch, closest_weed=None)
    assert spray_mod.spraying(make_drone_state(), make_frame()) == DroneStateEnum.RTL


def test_detection_in_range_sprays_weed(monkeypatch, make_drone_state, make_frame,
                                        make_detection, reset_state_globals):
    w = weed()
    db = setup_spray(monkeypatch, closest_weed=w, ned=(1.0, 0.5))  # dist ~1.1 m < 2 m

    result = spray_mod.spraying(make_drone_state(), make_frame(make_detection()))

    assert result == DroneStateEnum.GOTO
    assert db.sprayed_weeds == [w]
    assert db.traveled_weeds == []
    assert "spray_attempt" in logged_events()


def test_empty_frame_marks_miss(monkeypatch, make_drone_state, make_frame,
                                reset_state_globals):
    w = weed()
    db = setup_spray(monkeypatch, closest_weed=w)

    result = spray_mod.spraying(make_drone_state(), make_frame())

    assert result == DroneStateEnum.GOTO
    assert db.sprayed_weeds == []
    assert db.traveled_weeds == [w]  # skipped so goto picks the next one
    assert "spray_miss" in logged_events()


def test_far_detection_marks_miss(monkeypatch, make_drone_state, make_frame,
                                  make_detection, reset_state_globals):
    w = weed()
    db = setup_spray(monkeypatch, closest_weed=w, ned=(10.0, 10.0))  # ~14 m away

    result = spray_mod.spraying(make_drone_state(), make_frame(make_detection()))

    assert result == DroneStateEnum.GOTO
    assert db.sprayed_weeds == []
    assert db.traveled_weeds == [w]


def test_detection_at_exact_spray_error_sprays(monkeypatch, make_drone_state, make_frame,
                                               make_detection, reset_state_globals):
    # The spray gate is inclusive: dist == MIN_SPRAY_ERROR still counts.
    w = weed()
    db = setup_spray(monkeypatch, closest_weed=w, ned=(MIN_SPRAY_ERROR, 0.0))

    result = spray_mod.spraying(make_drone_state(), make_frame(make_detection()))

    assert result == DroneStateEnum.GOTO
    assert db.sprayed_weeds == [w]
    assert db.traveled_weeds == []


def test_one_in_range_detection_among_far_ones_sprays(monkeypatch, make_drone_state,
                                                      make_frame, make_detection,
                                                      reset_state_globals):
    # A single in-range detection must count as a spray (no miss/skip), even if
    # other detections in the same frame are far away.
    w = weed()
    db = setup_spray(monkeypatch, closest_weed=w)
    far = make_detection(px=100.0, py=100.0)
    close = make_detection(px=640.0, py=640.0)
    neds = {id(far): (10.0, 10.0), id(close): (0.5, 0.0)}
    monkeypatch.setattr(spray_mod, "detection_to_ned", lambda ds, det: neds[id(det)])

    result = spray_mod.spraying(make_drone_state(), make_frame(far, close))

    assert result == DroneStateEnum.GOTO
    assert db.sprayed_weeds == [w]
    assert db.traveled_weeds == []
    assert "spray_miss" not in logged_events()


def test_multiple_close_detections_mark_same_weed_repeatedly(monkeypatch, make_drone_state,
                                                             make_frame, make_detection,
                                                             reset_state_globals):
    # Locks in current behaviour: every in-range detection re-marks the same
    # closest weed (see code review M-finding — one spray event would suffice).
    w = weed()
    db = setup_spray(monkeypatch, closest_weed=w, ned=(0.5, 0.5))

    result = spray_mod.spraying(make_drone_state(),
                                make_frame(make_detection(), make_detection()))

    assert result == DroneStateEnum.GOTO
    assert db.sprayed_weeds == [w, w]
