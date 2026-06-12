"""
Pytest tests for the scan-data clustering logic in states/scan.py.

Covers:
  * Point.add_det      – running-centroid of a weed cluster
  * Point.dist_to_cord – haversine distance from cluster centroid to a point
  * prosess_all_scan_data – the full pipeline: back-project every detection,
    greedily cluster within MIN_WEED_SPACING, drop clusters with fewer than
    MIN_NUM_DET detections, and log the survivors as weeds.

states/scan.py imports telemetry (serial), DB_abstraction (SQLite) and
mission_logging (file I/O), so those are stubbed before import. We then drive
prosess_all_scan_data through a fake db_abstraction that yields synthetic
snapshots and records the weeds it would have written.

Run with:  python -m pytest tests/test_clustering.py
"""

import math
import sys
import time
import types
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

M_PER_DEG_LAT = 111_320.0
HOME_LAT = -35.363261
HOME_LON = 149.165230


# ---------------------------------------------------------------------------
# Stub the heavy modules states/scan.py pulls in, BEFORE importing it.
# ---------------------------------------------------------------------------

def _install_stubs():
    # telemetry – scan.py reads telemetry_singlton (only used by scan(), not by
    # the clustering function, but the import must succeed).
    tel = types.ModuleType("telemetry")
    tel.telemetry_singlton = MagicMock()
    sys.modules.setdefault("telemetry", tel)

    # mission_logging – capture log_event calls.
    ml = types.ModuleType("mission_logging")
    ml.log_event = MagicMock()
    sys.modules.setdefault("mission_logging", ml)

    # DB_abstraction – provide a real swappable singleton + a simple Weed type.
    dba = types.ModuleType("DB_abstraction")

    @dataclass
    class Weed:
        lat: float
        lon: float
        id: int = 0

    class _FakeDB:
        def __init__(self):
            self.snapshots = []
            self.logged_weeds = []

        def get_all_snapshots(self):
            return self.snapshots

        def log_weed(self, weed):
            self.logged_weeds.append(weed)

    dba.Weed = Weed
    dba.db_abstraction = _FakeDB()
    sys.modules["DB_abstraction"] = dba
    return dba, ml


_dba_mod, _ml_mod = _install_stubs()

# utils + drone_state + ai_class are the real ones (light, no side effects).
from ai_class import Detection, Frame  # noqa: E402
from drone_state import DroneStateForHoming, Rotation, GPSFix  # noqa: E402
import states.scan as scan  # noqa: E402

Point = scan.Point


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_state(lat=HOME_LAT, lon=HOME_LON, alt=10.0):
    """A telemetry-ready, level drone state hovering over (lat, lon)."""
    s = DroneStateForHoming()
    s.latitude = lat
    s.longitude = lon
    s.altitude_rel_home = alt
    s.width = 1280
    s.hight = 1280
    rot = Rotation(time_ns=0, x=0.0, y=0.0, z=0.0)
    s.rotaion = rot
    s.rotaion_history.append(rot)
    s.gps_history.append(GPSFix(time_ns=0, lat=lat, lon=lon, vx=0.0, vy=0.0))
    return s


def centre_detection(state):
    """Detection at the image centre → back-projects to directly below the drone."""
    cx, cy = state.width / 2.0, state.hight / 2.0
    return Detection(label="sports ball", confidence=0.9,
                     bbox=[(cx - 5, cy - 5), (cx + 5, cy + 5)], time_ns=0)


@dataclass
class _Snapshot:
    drone_state: DroneStateForHoming
    frame: Frame


def snapshot_over(weed_lat, weed_lon, alt=10.0):
    """A snapshot where the drone hovers over the weed and sees it dead-centre.

    Because the camera is nadir and level, the centre pixel back-projects to the
    drone's own lat/lon — so positioning the drone over the weed makes
    detection_to_latlon recover (weed_lat, weed_lon).
    """
    s = make_state(lat=weed_lat, lon=weed_lon, alt=alt)
    frame = Frame([centre_detection(s)], drone_state=s)
    return _Snapshot(s, frame)


def run_pipeline(snapshots):
    """Reset the fake DB, feed snapshots, run clustering, return logged weeds."""
    _dba_mod.db_abstraction.snapshots = snapshots
    _dba_mod.db_abstraction.logged_weeds = []
    scan.prosess_all_scan_data()
    return _dba_mod.db_abstraction.logged_weeds


# ---------------------------------------------------------------------------
# Point – the cluster accumulator
# ---------------------------------------------------------------------------

class TestPoint:
    def test_single_detection_centroid_is_the_point(self):
        p = Point()
        p.add_det(HOME_LAT, HOME_LON)
        assert p.location == (HOME_LAT, HOME_LON)
        assert len(p.det_location) == 1

    def test_centroid_is_running_average(self):
        p = Point()
        p.add_det(0.0, 0.0)
        p.add_det(2.0, 4.0)
        assert p.location == (1.0, 2.0)
        p.add_det(4.0, 5.0)
        assert p.location == pytest.approx((2.0, 3.0))

    def test_dist_to_cord_uses_haversine(self):
        p = Point()
        p.add_det(HOME_LAT, HOME_LON)
        north_5m = (HOME_LAT + 5.0 / M_PER_DEG_LAT, HOME_LON)
        assert p.dist_to_cord(north_5m) == pytest.approx(5.0, abs=0.05)

    def test_dist_to_self_is_zero(self):
        p = Point()
        p.add_det(HOME_LAT, HOME_LON)
        assert p.dist_to_cord((HOME_LAT, HOME_LON)) == 0.0


# ---------------------------------------------------------------------------
# prosess_all_scan_data – the full clustering pipeline
# ---------------------------------------------------------------------------

class TestClusteringPipeline:
    def test_no_snapshots_logs_no_weeds(self):
        assert run_pipeline([]) == []

    def test_cluster_below_threshold_is_dropped(self):
        # MIN_NUM_DET detections required; give it one fewer.
        snaps = [snapshot_over(HOME_LAT, HOME_LON) for _ in range(scan.MIN_NUM_DET - 1)]
        assert run_pipeline(snaps) == []

    def test_cluster_at_threshold_is_kept(self):
        snaps = [snapshot_over(HOME_LAT, HOME_LON) for _ in range(scan.MIN_NUM_DET)]
        weeds = run_pipeline(snaps)
        assert len(weeds) == 1
        assert weeds[0].lat == pytest.approx(HOME_LAT, abs=1e-7)
        assert weeds[0].lon == pytest.approx(HOME_LON, abs=1e-7)

    def test_two_well_separated_weeds_form_two_clusters(self):
        far_lat = HOME_LAT + 20.0 / M_PER_DEG_LAT      # 20 m apart >> MIN_WEED_SPACING
        snaps = ([snapshot_over(HOME_LAT, HOME_LON) for _ in range(scan.MIN_NUM_DET)] +
                 [snapshot_over(far_lat, HOME_LON) for _ in range(scan.MIN_NUM_DET)])
        weeds = run_pipeline(snaps)
        assert len(weeds) == 2

    def test_detections_within_spacing_merge_into_one(self):
        # Scatter detections within MIN_WEED_SPACING of each other → one cluster.
        jitter = (scan.MIN_WEED_SPACING * 0.3) / M_PER_DEG_LAT
        snaps = []
        for k in range(scan.MIN_NUM_DET + 2):
            offset = jitter if k % 2 else -jitter
            snaps.append(snapshot_over(HOME_LAT + offset, HOME_LON))
        weeds = run_pipeline(snaps)
        assert len(weeds) == 1
        # Centroid lands near home (the jitter averages out).
        assert weeds[0].lat == pytest.approx(HOME_LAT, abs=jitter)

    def test_merged_centroid_averages_member_detections(self):
        d = 0.5 / M_PER_DEG_LAT      # 0.5 m, comfortably inside MIN_WEED_SPACING
        lats = [HOME_LAT - d, HOME_LAT, HOME_LAT + d]
        snaps = [snapshot_over(lat, HOME_LON) for lat in lats]
        weeds = run_pipeline(snaps)
        assert len(weeds) == 1
        assert weeds[0].lat == pytest.approx(sum(lats) / len(lats), abs=1e-9)

    def test_non_finite_back_projection_is_skipped(self):
        # A snapshot whose drone state isn't telemetry-ready → detection_to_latlon
        # returns inf and the detection must be dropped, not clustered.
        good = [snapshot_over(HOME_LAT, HOME_LON) for _ in range(scan.MIN_NUM_DET)]
        bad_state = DroneStateForHoming()       # no rotation history → not ready
        bad_state.altitude_rel_home = 10.0
        bad = _Snapshot(bad_state, Frame([centre_detection(bad_state)]))
        weeds = run_pipeline(good + [bad])
        assert len(weeds) == 1                  # bad detection ignored

    def test_logs_weed_detected_event_per_weed(self):
        # Assert on scan's own bound log_event (other test modules may reassign
        # mission_logging.log_event after scan imported it).
        scan.log_event.reset_mock()
        snaps = [snapshot_over(HOME_LAT, HOME_LON) for _ in range(scan.MIN_NUM_DET)]
        run_pipeline(snaps)
        events = [c for c in scan.log_event.call_args_list
                  if c.args and c.args[0] == "weed_detected"]
        assert len(events) == 1
