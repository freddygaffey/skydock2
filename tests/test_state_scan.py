"""Tests for the scan() state function in states/scan.py.

(The clustering pipeline process_all_scan_data is covered separately in
tests/test_clustering.py; here it is mocked so scan()'s control flow can be
tested in isolation.)

Run with:  python -m pytest tests/test_state_scan.py
"""

import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.support import FakeTelemetry, FakeDB  # noqa: E402
import states.scan as scan_mod  # noqa: E402
from states.enum import DroneStateEnum  # noqa: E402
from constants import SCAN_HEIGHT, GOTO_ALT, MIN_DIST_FROM_WAYPOINT  # noqa: E402


def setup_scan(monkeypatch, waypoints=()):
    tel = FakeTelemetry()
    db = FakeDB()
    db.waypoints = list(waypoints)
    monkeypatch.setattr(scan_mod, "telemetry_singleton", tel)
    monkeypatch.setattr(scan_mod, "db_abstraction", db)
    monkeypatch.setattr(scan_mod, "process_all_scan_data", MagicMock())
    monkeypatch.setattr(time, "sleep", lambda s: None)  # scan() sleeps 10s after processing
    return tel, db


def waypoint(lat, lon, wp_id=1):
    return SimpleNamespace(lat=lat, lon=lon, id=wp_id)


def test_pending_waypoint_flies_at_scan_height(monkeypatch, make_drone_state, make_frame,
                                               reset_state_globals):
    state = make_drone_state(lat=-35.3632, lon=149.1652)
    wp = waypoint(-35.3640, 149.1660)  # ~120 m away
    tel, db = setup_scan(monkeypatch, [wp])

    result = scan_mod.scan(state, make_frame())

    assert result == DroneStateEnum.SCAN
    assert tel.fly_to_calls == [(wp.lat, wp.lon, SCAN_HEIGHT)]
    assert len(db.logged_states) == 1          # snapshot logged every tick
    assert db.traveled_waypoints == []         # too far to mark


def test_close_waypoint_marked_traveled(monkeypatch, make_drone_state, make_frame,
                                        reset_state_globals):
    state = make_drone_state(lat=-35.3632, lon=149.1652)
    wp = waypoint(state.latitude, state.longitude)  # directly underneath
    tel, db = setup_scan(monkeypatch, [wp])

    result = scan_mod.scan(state, make_frame())

    assert result == DroneStateEnum.SCAN
    assert db.traveled_waypoints == [wp]


def test_far_waypoint_not_marked(monkeypatch, make_drone_state, make_frame,
                                 reset_state_globals):
    state = make_drone_state()
    wp = waypoint(state.latitude + 0.001, state.longitude)  # ~111 m
    _, db = setup_scan(monkeypatch, [wp])

    scan_mod.scan(state, make_frame())

    assert db.traveled_waypoints == []


def test_waypoint_at_exact_min_dist_not_marked(monkeypatch, make_drone_state, make_frame,
                                               reset_state_globals):
    # The arrival gate is strict: dist == MIN_DIST_FROM_WAYPOINT is NOT arrival.
    state = make_drone_state()
    wp = waypoint(state.latitude, state.longitude)
    _, db = setup_scan(monkeypatch, [wp])
    monkeypatch.setattr(scan_mod, "haversine_distance",
                        lambda *a: MIN_DIST_FROM_WAYPOINT)

    scan_mod.scan(state, make_frame())

    assert db.traveled_waypoints == []


def test_waypoint_just_inside_min_dist_marked(monkeypatch, make_drone_state, make_frame,
                                              reset_state_globals):
    state = make_drone_state()
    wp = waypoint(state.latitude, state.longitude)
    _, db = setup_scan(monkeypatch, [wp])
    monkeypatch.setattr(scan_mod, "haversine_distance",
                        lambda *a: MIN_DIST_FROM_WAYPOINT - 0.01)

    scan_mod.scan(state, make_frame())

    assert db.traveled_waypoints == [wp]


def test_exhausted_tick_does_not_log_snapshot(monkeypatch, make_drone_state, make_frame,
                                              reset_state_globals):
    # Snapshots feed the clusterer; once waypoints are done nothing more is logged.
    state = make_drone_state()
    _, db = setup_scan(monkeypatch, waypoints=[])

    scan_mod.scan(state, make_frame())

    assert db.logged_states == []


def test_waypoints_exhausted_processes_once_and_goes_to_goto(monkeypatch, make_drone_state,
                                                             make_frame, reset_state_globals):
    state = make_drone_state(lat=-35.3632, lon=149.1652)
    tel, db = setup_scan(monkeypatch, waypoints=[])

    result = scan_mod.scan(state, make_frame())

    assert result == DroneStateEnum.GOTO
    # Holds position at GOTO_ALT while crunching the scan data.
    assert tel.fly_to_calls == [(state.latitude, state.longitude, GOTO_ALT)]
    scan_mod.process_all_scan_data.assert_called_once()
    assert scan_mod._scan_data_processed is True


def test_second_exhausted_tick_skips_reprocessing(monkeypatch, make_drone_state, make_frame,
                                                  reset_state_globals):
    state = make_drone_state()
    tel, db = setup_scan(monkeypatch, waypoints=[])

    scan_mod.scan(state, make_frame())
    result = scan_mod.scan(state, make_frame())

    assert result == DroneStateEnum.GOTO
    scan_mod.process_all_scan_data.assert_called_once()  # not called again
    assert len(tel.fly_to_calls) == 1                    # no second hold command
