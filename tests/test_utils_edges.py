"""Edge-case tests for utils.py geometry, complementing test_geometry_math.py.

Covers: haversine extremes, the rangefinder-vs-barometer altitude branch, the
ray-rejection guard, lat/lon dead-reckoning, and the attitude-interpolation
branches of DroneStateForHoming.

Run with:  python -m pytest tests/test_utils_edges.py
"""

import math
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# utils imports drone_state/ai_class only; stub telemetry defensively in case a
# sibling has not already.
_tel = types.ModuleType("telemetry")
_tel.telemetry_singleton = None
sys.modules.setdefault("telemetry", _tel)

from drone_state import DroneStateForHoming, Rotation, GPSFix  # noqa: E402
from ai_class import Detection  # noqa: E402
from utils import (  # noqa: E402
    haversine_distance, detection_to_ned, detection_to_dist, detection_to_latlon,
)

HOME_LAT = -35.363261
HOME_LON = 149.165230
EARTH_R = 6_371_000


def make_state(lat=HOME_LAT, lon=HOME_LON, alt=10.0, roll=0.0, pitch=0.0, yaw=0.0,
               rangefinder_m=0.0, ready=True, vx=0.0, vy=0.0):
    s = DroneStateForHoming()
    s.latitude = lat
    s.longitude = lon
    s.altitude_rel_home = alt
    s.rangefinder_m = rangefinder_m
    s.velocity_x = vx
    s.velocity_y = vy
    if ready:
        rot = Rotation(time_ns=0, x=roll, y=pitch, z=yaw)
        s.rotation = rot
        s.rotation_history.append(rot)
        s.gps_history.append(GPSFix(time_ns=0, lat=lat, lon=lon, vx=vx, vy=vy))
    return s


def centre_det(state, time_ns=0):
    cx, cy = state.width / 2.0, state.height / 2.0
    return Detection(label="sports ball", confidence=0.9,
                     bbox=[(cx - 5, cy - 5), (cx + 5, cy + 5)], time_ns=time_ns)


# ---------------------------------------------------------------------------
# haversine
# ---------------------------------------------------------------------------

def test_haversine_zero_distance():
    assert haversine_distance(HOME_LAT, HOME_LON, HOME_LAT, HOME_LON) == pytest.approx(0.0)


def test_haversine_is_symmetric():
    d1 = haversine_distance(0.0, 0.0, 10.0, 10.0)
    d2 = haversine_distance(10.0, 10.0, 0.0, 0.0)
    assert d1 == pytest.approx(d2)


def test_haversine_quarter_circumference():
    # (0,0) to (0,90) is a quarter of the way around the equator.
    d = haversine_distance(0.0, 0.0, 0.0, 90.0)
    assert d == pytest.approx(math.pi / 2 * EARTH_R, rel=1e-6)


def test_haversine_antimeridian_is_short():
    # 179.9 E to 179.9 W is 0.2 deg of longitude, not 359.8.
    d = haversine_distance(0.0, 179.9, 0.0, -179.9)
    expected = math.radians(0.2) * EARTH_R
    assert d == pytest.approx(expected, rel=1e-6)


def test_haversine_across_pole():
    d = haversine_distance(89.0, 0.0, 89.0, 180.0)
    expected = math.radians(2.0) * EARTH_R  # 1 deg to pole + 1 deg back
    assert d == pytest.approx(expected, rel=1e-6)


# ---------------------------------------------------------------------------
# detection_to_ned guards
# ---------------------------------------------------------------------------

def test_ned_returns_inf_when_not_ready():
    state = make_state(ready=False)
    det = Detection(label="ball", confidence=0.5, bbox=[(0, 0), (10, 10)], time_ns=0)
    n, e = detection_to_ned(state, det)
    assert math.isinf(n) and math.isinf(e)


def test_ned_rejects_steep_upward_ray():
    # A large pitch tilts the centre ray toward the horizon: ray_NED[2] < 0.3.
    state = make_state(pitch=math.radians(80))
    n, e = detection_to_ned(state, centre_det(state))
    assert math.isinf(n) and math.isinf(e)


def test_dist_propagates_inf():
    state = make_state(ready=False)
    det = Detection(label="ball", confidence=0.5, bbox=[(0, 0), (10, 10)], time_ns=0)
    assert math.isinf(detection_to_dist(state, det))


def test_rangefinder_overrides_barometric_alt():
    # Centre detection points straight down; range distance becomes the height.
    baro = make_state(alt=10.0, rangefinder_m=0.0)
    rng = make_state(alt=10.0, rangefinder_m=5.0)  # valid band 0.3..12

    # Straight-down centre ray => N,E both ~0 regardless, so compare a tilted ray.
    det_b = Detection(label="ball", confidence=0.9,
                      bbox=[(baro.width * 0.75, baro.height / 2),
                            (baro.width * 0.75 + 10, baro.height / 2 + 10)], time_ns=0)
    det_r = Detection(label="ball", confidence=0.9, bbox=det_b.bbox, time_ns=0)

    nb, eb = detection_to_ned(baro, det_b)
    nr, er = detection_to_ned(rng, det_r)
    # Lower effective height (5 m vs 10 m) => closer ground intersection.
    assert abs(nr) < abs(nb) or abs(er) < abs(eb)


def test_rangefinder_out_of_band_ignored():
    # 20 m is outside the 0.3..12 band, so altitude_rel_home is used instead.
    s_far = make_state(alt=10.0, rangefinder_m=20.0)
    s_baro = make_state(alt=10.0, rangefinder_m=0.0)
    det = Detection(label="ball", confidence=0.9,
                    bbox=[(s_far.width * 0.75, s_far.height / 2),
                          (s_far.width * 0.75 + 10, s_far.height / 2 + 10)], time_ns=0)
    assert detection_to_ned(s_far, det) == pytest.approx(detection_to_ned(s_baro, det))


# ---------------------------------------------------------------------------
# detection_to_latlon dead-reckoning
# ---------------------------------------------------------------------------

def test_latlon_centre_is_under_drone():
    state = make_state(alt=10.0)
    lat, lon = detection_to_latlon(state, centre_det(state))
    assert lat == pytest.approx(HOME_LAT, abs=1e-6)
    assert lon == pytest.approx(HOME_LON, abs=1e-6)


def test_latlon_dead_reckons_with_velocity():
    # Drone moving north; a detection timestamped later projects from a shifted fix.
    state = make_state(alt=10.0, vx=5.0)  # 5 m/s north
    state.gps_history.clear()
    state.gps_history.append(GPSFix(time_ns=0, lat=HOME_LAT, lon=HOME_LON, vx=5.0, vy=0.0))

    det_now = centre_det(state, time_ns=0)
    det_later = centre_det(state, time_ns=1_000_000_000)  # +1 s

    lat_now, _ = detection_to_latlon(state, det_now)
    lat_later, _ = detection_to_latlon(state, det_later)
    assert lat_later > lat_now  # moved north in the intervening second


# ---------------------------------------------------------------------------
# attitude history interpolation
# ---------------------------------------------------------------------------

def test_get_position_at_time_empty_history_fallback():
    s = make_state(ready=False)
    s.latitude, s.longitude = HOME_LAT, HOME_LON
    fix = s.get_position_at_time(1_000_000)
    assert fix.lat == pytest.approx(HOME_LAT)
    assert fix.lon == pytest.approx(HOME_LON)


def test_get_rotation_before_first_returns_current():
    s = make_state()
    s.rotation_history.clear()
    s.rotation = Rotation(time_ns=100, x=0.5, y=0.0, z=0.0)
    s.rotation_history.append(Rotation(time_ns=100, x=0.5, y=0.0, z=0.0))
    # Query before the first sample => falls back to self.rotation.
    rot = s.get_rotation_at_time(50)
    assert rot.x == pytest.approx(0.5)


def test_get_rotation_extrapolates_past_last():
    s = make_state()
    s.rotation_history.clear()
    s.rotation_history.append(Rotation(time_ns=0, x=0.0, y=0.0, z=0.0, dx=1.0))
    # 1 s later, extrapolated with dx=1 rad/s => x ~= 1.0.
    rot = s.get_rotation_at_time(1_000_000_000)
    assert rot.x == pytest.approx(1.0, rel=1e-6)


def test_get_rotation_interpolates_between_samples():
    s = make_state()
    s.rotation_history.clear()
    s.rotation_history.append(Rotation(time_ns=0, x=0.0, y=0.0, z=0.0))
    s.rotation_history.append(Rotation(time_ns=1_000_000_000, x=1.0, y=0.0, z=0.0))
    mid = s.get_rotation_at_time(500_000_000)
    assert 0.0 < mid.x < 1.0  # Hermite midpoint between the two samples
