"""Tests locking in the MEASURED camera pixel->body mapping (drone_state.CAM_TO_BODY).

EXPERIMENTAL mapping, July 2026: image-right = body-BACKWARD (x mirrored),
image-down = body-RIGHT. Verified on May-era flight logs by three independent
methods (tools/camera_orientation_from_flow.py, docs/Bug Notes.md); to be
confirmed on the current 640x640 config's first flight.

These tests pin BOTH directions (utils.detection_to_ned / utils.latlon_to_pixel)
and the sim generator (sim_ai._project_latlon_to_pixel) to the same constant, so
sim and real can never silently diverge again.

Run with:  python -m pytest tests/test_cam_to_body_mapping.py
"""

import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from drone_state import CAM_TO_BODY  # noqa: E402
from utils import detection_to_ned, detection_to_latlon, latlon_to_pixel  # noqa: E402


def test_constant_is_the_measured_mirror():
    # ray_body = CAM_TO_BODY @ [x_cam, y_cam, 1]: x flipped, y kept, z kept.
    assert np.allclose(np.array(CAM_TO_BODY), np.diag([-1.0, 1.0, 1.0]))


def test_ball_ahead_appears_image_left(make_drone_state, make_detection):
    # yaw 0, level, 10 m: a detection LEFT of centre is body-forward (north).
    s = make_drone_state(alt=10.0)
    n, e = detection_to_ned(s, make_detection(px=s.width / 2 - 100, py=s.height / 2))
    assert n > 0.5
    assert abs(e) < 0.05


def test_ball_image_down_is_body_right(make_drone_state, make_detection):
    # image-down (+py) was and remains body-right (east at yaw 0).
    s = make_drone_state(alt=10.0)
    n, e = detection_to_ned(s, make_detection(px=s.width / 2, py=s.height / 2 + 200))
    assert e > 0.5
    assert abs(n) < 0.05


def test_utils_roundtrip_pixel_latlon_pixel(make_drone_state, make_detection):
    # detection -> latlon -> pixel must return the original pixel, including
    # with non-trivial attitude, or the two mappings have diverged.
    s = make_drone_state(alt=12.0, yaw=0.7, roll=0.03, pitch=-0.02)
    px0, py0 = 500.0, 780.0
    lat, lon = detection_to_latlon(s, make_detection(px=px0, py=py0))
    out = latlon_to_pixel(s, lat, lon, time_ns=0)
    assert out is not None
    assert out[0] == pytest.approx(px0, abs=0.5)
    assert out[1] == pytest.approx(py0, abs=0.5)


def test_sim_generator_matches_utils_projection(make_drone_state, make_detection):
    # A weed 3 m north must land on a pixel that utils projects BACK to 3 m north.
    import sim_ai

    s = make_drone_state(alt=10.0)
    fx, fy, cx, cy = sim_ai._camera_intrinsics(s)
    weed_lat = s.latitude + 3.0 / 111_320.0
    proj = sim_ai._project_latlon_to_pixel(s, weed_lat, s.longitude, fx, fy, cx, cy)
    assert proj is not None
    u, v = proj
    assert u < cx  # north = image-left under the measured mapping
    n, e = detection_to_ned(s, make_detection(px=u, py=v))
    assert n == pytest.approx(3.0, abs=0.05)
    assert e == pytest.approx(0.0, abs=0.05)
