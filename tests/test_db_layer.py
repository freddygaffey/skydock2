"""Tests for DB_abstraction.DBAbstraction against a real temp SQLite file.

The fresh_db fixture (tests/conftest.py) points DB at a tmp file, resets the
DatabaseSession singleton, and disposes the engine afterwards.

Run with:  python -m pytest tests/test_db_layer.py
"""

import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.support import ensure_real_module  # noqa: E402

# Use the real modules (a sibling test may have stubbed them).
ensure_real_module("mission_logging")
dba_mod = ensure_real_module("DB_abstraction")
Waypoint = dba_mod.Waypoint
Weed = dba_mod.Weed

from drone_state import DroneStateForHoming, Rotation  # noqa: E402
from ai_class import Detection, Frame  # noqa: E402

HOME_LAT = -35.363261
HOME_LON = 149.165230


def drone_at(lat=HOME_LAT, lon=HOME_LON):
    s = DroneStateForHoming()
    s.latitude = lat
    s.longitude = lon
    return s


# ---------------------------------------------------------------------------
# Waypoints
# ---------------------------------------------------------------------------

def test_waypoint_add_and_get_roundtrip(fresh_db):
    wp = Waypoint(lat=HOME_LAT, lon=HOME_LON)
    wp_id = fresh_db.add_waypoint(wp)
    fetched = fresh_db.get_waypoint(wp_id)
    assert fetched is not None
    assert fetched.lat == pytest.approx(HOME_LAT)
    assert fetched.lon == pytest.approx(HOME_LON)
    assert fetched.visited is False


def test_get_next_waypoint_orders_by_id_and_skips_traveled(fresh_db):
    a = Waypoint(lat=1.0, lon=1.0)
    b = Waypoint(lat=2.0, lon=2.0)
    fresh_db.add_waypoint(a)
    fresh_db.add_waypoint(b)

    first = fresh_db.get_next_waypoint()
    assert first.lat == pytest.approx(1.0)

    fresh_db.mark_waypoint_traveled(first)
    second = fresh_db.get_next_waypoint()
    assert second.lat == pytest.approx(2.0)

    fresh_db.mark_waypoint_traveled(second)
    assert fresh_db.get_next_waypoint() is None


def test_get_all_waypoints(fresh_db):
    for i in range(3):
        fresh_db.add_waypoint(Waypoint(lat=float(i), lon=float(i)))
    assert len(fresh_db.get_all_waypoints()) == 3


# ---------------------------------------------------------------------------
# Weeds
# ---------------------------------------------------------------------------

def test_weed_log_and_get(fresh_db):
    wid = fresh_db.log_weed(Weed(lat=HOME_LAT, lon=HOME_LON, confidence=0.8))
    w = fresh_db.get_weed(wid)
    assert w.confidence == pytest.approx(0.8)
    assert w.sprayed is False


def test_get_all_weeds_filtered_by_sprayed(fresh_db):
    fresh_db.log_weed(Weed(lat=1.0, lon=1.0))
    w2 = Weed(lat=2.0, lon=2.0)
    fresh_db.log_weed(w2)
    fresh_db.mark_weed_sprayed(w2)

    assert len(fresh_db.get_all_weeds()) == 2
    assert len(fresh_db.get_all_weeds(sprayed=False)) == 1
    assert len(fresh_db.get_all_weeds(sprayed=True)) == 1


def test_get_closest_weed_picks_nearest_unsprayed(fresh_db):
    near = Weed(lat=HOME_LAT + 0.0001, lon=HOME_LON)   # ~11 m
    far = Weed(lat=HOME_LAT + 0.001, lon=HOME_LON)     # ~111 m
    fresh_db.log_weed(far)
    fresh_db.log_weed(near)

    closest = fresh_db.get_closest_weed(drone_at())
    assert closest.lat == pytest.approx(near.lat)


def test_get_closest_weed_respects_sprayed_and_traveled_filters(fresh_db):
    near = Weed(lat=HOME_LAT + 0.0001, lon=HOME_LON)
    far = Weed(lat=HOME_LAT + 0.001, lon=HOME_LON)
    fresh_db.log_weed(near)
    fresh_db.log_weed(far)
    fresh_db.mark_weed_sprayed(near)

    # Nearest unsprayed is now the far one.
    closest = fresh_db.get_closest_weed(drone_at())
    assert closest.lat == pytest.approx(far.lat)

    fresh_db.mark_weed_traveled(far)
    assert fresh_db.get_closest_weed(drone_at()) is None


def test_get_closest_weed_empty_returns_none(fresh_db):
    assert fresh_db.get_closest_weed(drone_at()) is None


# ---------------------------------------------------------------------------
# Snapshots (drone state + detections roundtrip)
# ---------------------------------------------------------------------------

def make_state_with_attitude():
    s = DroneStateForHoming()
    s.latitude = HOME_LAT
    s.longitude = HOME_LON
    s.altitude_rel_home = 12.5
    s.time_updated_GLOBAL_POSITION_INT = 1.0
    s.heading = None  # exercise the nullable column
    s.rotation = Rotation(time_ns=0, x=0.1, y=0.2, z=0.3, dx=0.01, dy=0.02, dz=0.03)
    return s


def test_snapshot_roundtrip_preserves_state_and_detections(fresh_db):
    state = make_state_with_attitude()
    det = Detection(label="sports ball", confidence=0.9,
                    bbox=[(100.0, 110.0), (140.0, 160.0)], track_id=7, time_ns=12345)
    fresh_db.log_drone_state_and_frame(state, Frame([det], photo_path="img/0001.jpg"))

    snaps = fresh_db.get_all_snapshots()
    assert len(snaps) == 1
    snap = snaps[0]

    ds = snap.drone_state
    assert ds.latitude == pytest.approx(HOME_LAT)
    assert ds.altitude_rel_home == pytest.approx(12.5)
    assert ds.heading is None
    assert ds.rotation.x == pytest.approx(0.1)
    assert ds.rotation.dz == pytest.approx(0.03)
    # Reconstructed states are seeded so projection code treats them as ready.
    assert ds.is_telemetry_ready is True

    assert len(snap.frame.detection) == 1
    rdet = snap.frame.detection[0]
    assert rdet.label == "sports ball"
    assert rdet.time_ns == 12345
    # bbox min/max corners survive the normalize-to-corners roundtrip.
    xs = [p[0] for p in rdet.bbox]
    ys = [p[1] for p in rdet.bbox]
    assert min(xs) == pytest.approx(100.0)
    assert max(xs) == pytest.approx(140.0)
    assert min(ys) == pytest.approx(110.0)
    assert max(ys) == pytest.approx(160.0)
    assert snap.frame.photo_path == "img/0001.jpg"


def test_get_latest_snapshot_returns_most_recent(fresh_db):
    s1 = make_state_with_attitude()
    s1.time_updated_GLOBAL_POSITION_INT = 1.0
    s2 = make_state_with_attitude()
    s2.time_updated_GLOBAL_POSITION_INT = 2.0
    s2.altitude_rel_home = 20.0
    fresh_db.log_drone_state_and_frame(s1, Frame([]))
    fresh_db.log_drone_state_and_frame(s2, Frame([]))

    latest = fresh_db.get_latest_snapshot()
    assert latest.drone_state.altitude_rel_home == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# Stats / backup / clear
# ---------------------------------------------------------------------------

def test_get_stats_counts(fresh_db):
    fresh_db.add_waypoint(Waypoint(lat=1.0, lon=1.0))
    fresh_db.log_weed(Weed(lat=1.0, lon=1.0))
    fresh_db.log_drone_state_and_frame(make_state_with_attitude(), Frame([]))

    stats = fresh_db.get_stats()
    assert stats["total_waypoints"] == 1
    assert stats["total_weeds"] == 1
    assert stats["unsprayed_weeds"] == 1
    assert stats["total_snapshots"] == 1


def test_backup_and_clear_writes_json_and_empties_db(fresh_db, tmp_path):
    fresh_db.add_waypoint(Waypoint(lat=1.0, lon=2.0))
    fresh_db.log_weed(Weed(lat=3.0, lon=4.0))
    fresh_db.log_drone_state_and_frame(make_state_with_attitude(), Frame([]))

    backup_path = fresh_db.backup_and_clear(backup_dir=str(tmp_path / "backups"))

    data = json.loads(Path(backup_path).read_text())
    assert len(data["waypoints"]) == 1
    assert len(data["weeds"]) == 1
    assert len(data["snapshots"]) == 1

    stats = fresh_db.get_stats()
    assert stats["total_waypoints"] == 0
    assert stats["total_weeds"] == 0
    assert stats["total_snapshots"] == 0


def test_database_session_is_singleton(fresh_db):
    DB = ensure_real_module("DB")
    assert DB.DatabaseSession() is DB.DatabaseSession()
