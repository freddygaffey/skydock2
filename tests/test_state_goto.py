"""Tests for the goto() state function in states/goto.py.

Run with:  python -m pytest tests/test_state_goto.py
"""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.support import FakeTelemetry, FakeDB  # noqa: E402
import states.goto as goto_mod  # noqa: E402
import states.shared_data as shared_data  # noqa: E402
from states.enum import DroneStateEnum  # noqa: E402
from constants import GOTO_ALT, MAX_HOMING_DIST  # noqa: E402


def setup_goto(monkeypatch, closest_weed=None):
    tel = FakeTelemetry()
    db = FakeDB()
    db.closest_weed = closest_weed
    monkeypatch.setattr(goto_mod, "telemetry_singleton", tel)
    monkeypatch.setattr(goto_mod, "db_abstraction", db)
    return tel, db


def weed(lat, lon, weed_id=1):
    return SimpleNamespace(lat=lat, lon=lon, id=weed_id)


def test_no_weeds_left_returns_rtl(monkeypatch, make_drone_state, make_frame,
                                   reset_state_globals):
    state = make_drone_state()
    _, db = setup_goto(monkeypatch, closest_weed=None)

    assert goto_mod.goto(state, make_frame()) == DroneStateEnum.RTL
    assert db.traveled_weeds == []


def test_weed_within_homing_distance_starts_homing(monkeypatch, make_drone_state, make_frame,
                                                   reset_state_globals):
    state = make_drone_state(lat=-35.3632, lon=149.1652)
    w = weed(state.latitude, state.longitude)  # 0 m < MAX_HOMING_DIST
    tel, db = setup_goto(monkeypatch, closest_weed=w)

    result = goto_mod.goto(state, make_frame())

    assert result == DroneStateEnum.HOMING
    assert db.traveled_weeds == [w]
    assert tel.fly_to_calls == []  # no fly command once homing takes over


def test_far_weed_flies_toward_it(monkeypatch, make_drone_state, make_frame,
                                  reset_state_globals):
    state = make_drone_state(lat=-35.3632, lon=149.1652)
    w = weed(state.latitude + 0.001, state.longitude)  # ~111 m away
    tel, db = setup_goto(monkeypatch, closest_weed=w)

    result = goto_mod.goto(state, make_frame())

    assert result == DroneStateEnum.GOTO
    assert tel.fly_to_calls == [(w.lat, w.lon, GOTO_ALT)]
    assert db.traveled_weeds == []


def test_weed_at_exact_homing_distance_keeps_flying(monkeypatch, make_drone_state, make_frame,
                                                    reset_state_globals):
    # The handoff gate is strict: dist == MAX_HOMING_DIST must NOT start homing.
    state = make_drone_state()
    w = weed(state.latitude, state.longitude)
    tel, db = setup_goto(monkeypatch, closest_weed=w)
    monkeypatch.setattr(goto_mod, "haversine_distance", lambda *a: MAX_HOMING_DIST)

    result = goto_mod.goto(state, make_frame())

    assert result == DroneStateEnum.GOTO
    assert db.traveled_weeds == []
    assert tel.fly_to_calls == [(w.lat, w.lon, GOTO_ALT)]


def test_weed_just_inside_homing_distance_hands_off(monkeypatch, make_drone_state, make_frame,
                                                    reset_state_globals):
    state = make_drone_state()
    w = weed(state.latitude, state.longitude)
    tel, db = setup_goto(monkeypatch, closest_weed=w)
    monkeypatch.setattr(goto_mod, "haversine_distance", lambda *a: MAX_HOMING_DIST - 0.01)

    result = goto_mod.goto(state, make_frame())

    assert result == DroneStateEnum.HOMING
    assert db.traveled_weeds == [w]
    assert tel.fly_to_calls == []


def test_goto_updates_shared_timestamp(monkeypatch, make_drone_state, make_frame,
                                       reset_state_globals):
    state = make_drone_state()
    setup_goto(monkeypatch, closest_weed=None)
    before = shared_data.last_goto_time

    goto_mod.goto(state, make_frame())

    assert shared_data.last_goto_time != before
    assert shared_data.last_goto_time > 0
