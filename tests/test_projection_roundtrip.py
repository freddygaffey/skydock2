"""
Round-trip test: sim camera projection <-> utils back-projection.

Places weeds at known GPS offsets, has sim_ai project them into camera
pixels, then asserts utils.detection_to_latlon recovers the original
lat/lon. Guards the agreement between sim_ai and utils — if anyone
changes the camera model on one side only, this screams.

Pure math: no SITL, no Hailo, no MAVLink connection, no files written.
Run with:  python tests/test_projection_roundtrip.py
"""

import math
import sys
import time
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Stub the two modules with side effects: telemetry pulls in pyserial and
# sim_ai only reads telemetry_singleton (None until main.py sets it);
# mission_logging would try to write mission.jsonl.
_tel = types.ModuleType("telemetry")
_tel.telemetry_singleton = None
sys.modules.setdefault("telemetry", _tel)

_ml = types.ModuleType("mission_logging")
_ml.log_event = MagicMock()
sys.modules.setdefault("mission_logging", _ml)

import sim_ai  # noqa: E402
from drone_state import DroneStateForHoming, Rotation, GPSFix  # noqa: E402
from utils import detection_to_latlon, haversine_distance  # noqa: E402


HOME_LAT = -35.363261
HOME_LON = 149.165230

ALTITUDES = (3.0, 5.0, 10.0, 15.0)

# roll, pitch, yaw in radians
ATTITUDES = (
    (0.0, 0.0, 0.0),
    (0.1, 0.0, 0.0),
    (0.0, -0.1, 0.0),
    (0.05, 0.05, math.radians(45)),
    (-0.08, 0.06, math.radians(170)),
)

# Ground offsets as a fraction of altitude (north, east). Kept well inside
# the footprint so bboxes are never clamped at the image border, which
# would shift the bbox centre and break the round trip by design.
OFFSET_FRACS = ((0.0, 0.0), (0.05, 0.0), (0.0, -0.05), (0.1, 0.1), (-0.15, 0.08))

TOLERANCE_M = 0.02


def make_state(lat, lon, alt, roll=0.0, pitch=0.0, yaw=0.0) -> DroneStateForHoming:
    now = time.time_ns()
    s = DroneStateForHoming()
    s.latitude = lat
    s.longitude = lon
    s.altitude_rel_home = alt
    s.width = sim_ai.NUM_OF_PIX_X
    s.height = sim_ai.NUM_OF_PIX_Y
    rot = Rotation(time_ns=now, x=roll, y=pitch, z=yaw)
    s.rotation = rot
    s.rotation_history.append(rot)  # makes is_telemetry_ready True
    s.gps_history.append(GPSFix(time_ns=now, lat=lat, lon=lon, vx=0.0, vy=0.0))
    return s


class TestProjectionRoundTrip(unittest.TestCase):
    def test_sim_pixel_back_projects_to_weed_latlon(self):
        checked = 0
        for alt in ALTITUDES:
            for roll, pitch, yaw in ATTITUDES:
                state = make_state(HOME_LAT, HOME_LON, alt, roll, pitch, yaw)
                for n_frac, e_frac in OFFSET_FRACS:
                    n_m = n_frac * alt
                    e_m = e_frac * alt
                    weed_lat = HOME_LAT + n_m / 111_320.0
                    weed_lon = HOME_LON + e_m / (111_320.0 * math.cos(math.radians(HOME_LAT)))

                    dets = sim_ai._visible_weed_detections(
                        state, [{"id": 0, "lat": weed_lat, "lon": weed_lon}]
                    )
                    if not dets:
                        # Tilt can push an off-centre weed out of frame — fine.
                        continue

                    # A bbox clipped at the image border has its centre shifted
                    # by design (real detectors do the same to half-visible
                    # objects), so it can't round-trip exactly — skip those.
                    (x0, y0), (x1, y1) = dets[0].bbox
                    if (x0 <= 0 or y0 <= 0
                            or x1 >= sim_ai.NUM_OF_PIX_X - 1
                            or y1 >= sim_ai.NUM_OF_PIX_Y - 1):
                        continue

                    rec_lat, rec_lon = detection_to_latlon(state, dets[0])
                    err_m = haversine_distance(weed_lat, weed_lon, rec_lat, rec_lon)
                    self.assertLess(
                        err_m, TOLERANCE_M,
                        f"round-trip error {err_m:.3f} m at alt={alt} "
                        f"rpy=({roll},{pitch},{yaw}) offset=({n_m:.2f},{e_m:.2f}) m",
                    )
                    checked += 1

        # The loop must not have silently skipped everything
        self.assertGreater(checked, 50)

    def test_weed_directly_below_level_drone_is_exact_centre(self):
        state = make_state(HOME_LAT, HOME_LON, 10.0)
        dets = sim_ai._visible_weed_detections(
            state, [{"id": 0, "lat": HOME_LAT, "lon": HOME_LON}]
        )
        self.assertEqual(len(dets), 1)
        u, v = dets[0].get_center()
        self.assertAlmostEqual(u, sim_ai.NUM_OF_PIX_X / 2.0, places=6)
        self.assertAlmostEqual(v, sim_ai.NUM_OF_PIX_Y / 2.0, places=6)

    def test_sim_and_utils_use_same_fov(self):
        """The lens model must come from DroneStateForHoming on both sides."""
        state = make_state(HOME_LAT, HOME_LON, 10.0)
        cam = sim_ai._vision_params(state)["camera"]
        self.assertAlmostEqual(cam["fov_x_deg"], state.fov_x_deg)
        self.assertAlmostEqual(cam["fov_y_deg"], state.fov_y_deg)


if __name__ == "__main__":
    unittest.main()
