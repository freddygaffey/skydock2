"""
Pytest tests for the coordinate / camera math in utils.py.

Covers:
  * haversine_distance      – great-circle distance
  * detection_to_ned        – pixel -> local North/East offset
  * detection_to_latlon     – pixel -> GPS
  * latlon_to_pixel         – GPS  -> pixel (inverse projection)

These are pure-math tests: no SITL, no MAVLink, no Hailo, no files.
Run with:  python -m pytest tests/test_geometry_math.py
"""

import math
import sys
import time
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# utils itself only pulls in ai_class + drone_state (both light), but be defensive
# about anything that might try to open a serial port / write a log.
sys.modules.setdefault("mission_logging", types.ModuleType("mission_logging"))
sys.modules["mission_logging"].log_event = MagicMock()
_tel = types.ModuleType("telemetry")
_tel.telemetry_singlton = None
sys.modules.setdefault("telemetry", _tel)

from ai_class import Detection  # noqa: E402
from drone_state import DroneStateForHoming, Rotation, GPSFix  # noqa: E402
from utils import (  # noqa: E402
    detection_to_ned,
    detection_to_latlon,
    latlon_to_pixel,
    haversine_distance,
)

HOME_LAT = -35.363261
HOME_LON = 149.165230
M_PER_DEG_LAT = 111_320.0


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def make_state(lat=HOME_LAT, lon=HOME_LON, alt=10.0,
               roll=0.0, pitch=0.0, yaw=0.0,
               width=1280, height=1280, rangefinder_m=0.0):
    """A telemetry-ready drone state at a fixed attitude (time_ns=0)."""
    s = DroneStateForHoming()
    s.latitude = lat
    s.longitude = lon
    s.altitude_rel_home = alt
    s.width = width
    s.hight = height
    s.rangefinder_m = rangefinder_m
    rot = Rotation(time_ns=0, x=roll, y=pitch, z=yaw)
    s.rotaion = rot
    s.rotaion_history.append(rot)          # makes is_telemetry_ready True
    s.gps_history.append(GPSFix(time_ns=0, lat=lat, lon=lon, vx=0.0, vy=0.0))
    return s


def centre_detection(state):
    """A detection whose bbox centre is the principal point (image centre)."""
    cx = state.width / 2.0
    cy = state.hight / 2.0
    return Detection(label="sports ball", confidence=0.9,
                     bbox=[(cx - 5, cy - 5), (cx + 5, cy + 5)], time_ns=0)


def pixel_detection(state, px, py):
    return Detection(label="sports ball", confidence=0.9,
                     bbox=[(px - 5, py - 5), (px + 5, py + 5)], time_ns=0)


# ---------------------------------------------------------------------------
# haversine_distance
# ---------------------------------------------------------------------------

class TestHaversine:
    def test_zero_distance_for_same_point(self):
        assert haversine_distance(HOME_LAT, HOME_LON, HOME_LAT, HOME_LON) == 0.0

    def test_one_degree_latitude_is_about_111km(self):
        d = haversine_distance(0.0, 0.0, 1.0, 0.0)
        # R*pi/180 = 6371000 * pi/180 ≈ 111194.9 m
        assert d == pytest.approx(111_194.9, abs=1.0)

    def test_symmetric(self):
        a = haversine_distance(HOME_LAT, HOME_LON, HOME_LAT + 0.01, HOME_LON + 0.02)
        b = haversine_distance(HOME_LAT + 0.01, HOME_LON + 0.02, HOME_LAT, HOME_LON)
        assert a == pytest.approx(b)

    def test_small_north_offset_matches_flat_earth(self):
        # 5 m north of home
        d_north = 5.0
        lat2 = HOME_LAT + d_north / M_PER_DEG_LAT
        d = haversine_distance(HOME_LAT, HOME_LON, lat2, HOME_LON)
        assert d == pytest.approx(d_north, abs=0.01)

    def test_small_east_offset_accounts_for_latitude(self):
        # 5 m east: a degree of longitude shrinks by cos(lat)
        d_east = 5.0
        lon2 = HOME_LON + d_east / (M_PER_DEG_LAT * math.cos(math.radians(HOME_LAT)))
        d = haversine_distance(HOME_LAT, HOME_LON, HOME_LAT, lon2)
        assert d == pytest.approx(d_east, abs=0.02)

    def test_triangle_inequality(self):
        a = (HOME_LAT, HOME_LON)
        b = (HOME_LAT + 0.001, HOME_LON)
        c = (HOME_LAT + 0.001, HOME_LON + 0.001)
        ab = haversine_distance(*a, *b)
        bc = haversine_distance(*b, *c)
        ac = haversine_distance(*a, *c)
        assert ac <= ab + bc + 1e-6


# ---------------------------------------------------------------------------
# detection_to_ned
# ---------------------------------------------------------------------------

class TestDetectionToNed:
    def test_not_ready_returns_inf(self):
        s = DroneStateForHoming()            # no rotation history → not ready
        s.altitude_rel_home = 10.0
        n, e = detection_to_ned(s, centre_detection(s))
        assert n == float("inf") and e == float("inf")

    def test_centre_pixel_level_drone_is_directly_below(self):
        s = make_state(alt=10.0)
        n, e = detection_to_ned(s, centre_detection(s))
        assert n == pytest.approx(0.0, abs=1e-6)
        assert e == pytest.approx(0.0, abs=1e-6)

    def test_ned_scales_with_altitude(self):
        # Same off-centre pixel, twice the altitude → twice the ground offset.
        det_px = None
        s1 = make_state(alt=10.0)
        s2 = make_state(alt=20.0)
        px, py = s1.width / 2.0 + 200, s1.hight / 2.0
        n1, e1 = detection_to_ned(s1, pixel_detection(s1, px, py))
        n2, e2 = detection_to_ned(s2, pixel_detection(s2, px, py))
        assert math.hypot(n2, e2) == pytest.approx(2 * math.hypot(n1, e1), rel=1e-6)

    def test_pixel_right_of_centre_maps_to_north(self):
        # detection_to_ned: N ∝ (u - cx), E ∝ (v - cy). A pixel to the right
        # (+u, same row) is North-positive with ~zero East.
        s = make_state(alt=10.0, yaw=0.0)
        px = s.width / 2.0 + 300
        py = s.hight / 2.0
        n, e = detection_to_ned(s, pixel_detection(s, px, py))
        assert n > 0
        assert abs(e) < abs(n)

    def test_pixel_below_centre_maps_to_east(self):
        # +v (down the image) is East-positive with ~zero North.
        s = make_state(alt=10.0, yaw=0.0)
        px = s.width / 2.0
        py = s.hight / 2.0 + 300
        n, e = detection_to_ned(s, pixel_detection(s, px, py))
        assert e > 0
        assert abs(n) < abs(e)


# ---------------------------------------------------------------------------
# latlon_to_pixel  (forward projection, the inverse of detection_to_ned)
# ---------------------------------------------------------------------------

class TestLatLonToPixel:
    def test_weed_directly_below_projects_to_centre(self):
        s = make_state(alt=10.0)
        px, py = latlon_to_pixel(s, HOME_LAT, HOME_LON, time_ns=0)
        assert px == pytest.approx(s.width / 2.0, abs=1e-3)
        assert py == pytest.approx(s.hight / 2.0, abs=1e-3)

    def test_far_away_weed_is_not_visible(self):
        s = make_state(alt=10.0)
        far_lat = HOME_LAT + 1000.0 / M_PER_DEG_LAT     # 1 km north
        assert latlon_to_pixel(s, far_lat, HOME_LON, time_ns=0) is None

    def test_weed_to_the_north_projects_right_of_centre(self):
        # Forward projection mirrors detection_to_ned: North maps to the +u (px) axis.
        s = make_state(alt=10.0, yaw=0.0)
        north_lat = HOME_LAT + 2.0 / M_PER_DEG_LAT
        result = latlon_to_pixel(s, north_lat, HOME_LON, time_ns=0)
        assert result is not None
        px, py = result
        assert px > s.width / 2.0
        assert py == pytest.approx(s.hight / 2.0, abs=1e-3)

    def test_weed_to_the_east_projects_below_centre(self):
        # East maps to the +v (py) axis.
        s = make_state(alt=10.0, yaw=0.0)
        east_lon = HOME_LON + 2.0 / (M_PER_DEG_LAT * math.cos(math.radians(HOME_LAT)))
        result = latlon_to_pixel(s, HOME_LAT, east_lon, time_ns=0)
        assert result is not None
        px, py = result
        assert py > s.hight / 2.0
        assert px == pytest.approx(s.width / 2.0, abs=1e-3)

    def test_zero_altitude_returns_none(self):
        s = make_state(alt=0.0)
        assert latlon_to_pixel(s, HOME_LAT, HOME_LON, time_ns=0) is None


# ---------------------------------------------------------------------------
# Round-trip: latlon_to_pixel -> detection_to_latlon should recover the weed
# ---------------------------------------------------------------------------

class TestProjectionRoundTrip:
    @pytest.mark.parametrize("alt", [3.0, 5.0, 10.0, 15.0])
    @pytest.mark.parametrize("roll,pitch,yaw", [
        (0.0, 0.0, 0.0),
        (0.1, 0.0, 0.0),
        (0.0, -0.1, 0.0),
        (0.05, 0.05, math.radians(45)),
        (-0.08, 0.06, math.radians(170)),
    ])
    @pytest.mark.parametrize("n_frac,e_frac", [
        (0.0, 0.0), (0.05, 0.0), (0.0, -0.05), (0.1, 0.1), (-0.15, 0.08),
    ])
    def test_pixel_then_latlon_recovers_weed(self, alt, roll, pitch, yaw, n_frac, e_frac):
        s = make_state(alt=alt, roll=roll, pitch=pitch, yaw=yaw)
        n_m, e_m = n_frac * alt, e_frac * alt
        weed_lat = HOME_LAT + n_m / M_PER_DEG_LAT
        weed_lon = HOME_LON + e_m / (M_PER_DEG_LAT * math.cos(math.radians(HOME_LAT)))

        px = latlon_to_pixel(s, weed_lat, weed_lon, time_ns=0)
        if px is None:
            pytest.skip("weed not in frame at this attitude/offset")

        det = pixel_detection(s, px[0], px[1])
        rec_lat, rec_lon = detection_to_latlon(s, det)
        err_m = haversine_distance(weed_lat, weed_lon, rec_lat, rec_lon)
        assert err_m < 0.05, f"round-trip error {err_m:.3f} m"
