"""Tests for the pure-math core of tools/camera_orientation_from_flow.py.

The flow/rotation measurement needs real frames, but the candidate signature
table it matches against is pure geometry — lock that down so a sign error
can't silently flip the verdict.
"""

import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from camera_orientation_from_flow import CANDIDATES, signature  # noqa: E402

FX, FY = 1222.0, 2292.0  # 1280px at 55.3 x 31.2 deg


def test_candidates_are_orthogonal_with_expected_handedness():
    for name, R in CANDIDATES.items():
        assert np.allclose(R @ R.T, np.eye(3), atol=1e-12), name
        det = np.linalg.det(R)
        if name.startswith("mirror"):
            assert math.isclose(det, -1.0, abs_tol=1e-12), name
        else:
            assert math.isclose(det, 1.0, abs_tol=1e-12), name


def test_identity_signature():
    # img-right = body-forward: flying forward streams the scene toward -u,
    # and a proper mapping rotates the scene OPPOSITE to the compass.
    u, v, hand = signature(np.eye(3), FX, FY)
    assert u < -100 and abs(v) < 1
    assert hand == -1


def test_mirror90_signature():
    # The May-2026 measured mapping: forward -> +u flow, mirrored handedness.
    u, v, hand = signature(CANDIDATES["mirror90  (img-right=BACK, img-down=RIGHT)"], FX, FY)
    assert u > 100 and abs(v) < 1
    assert hand == +1


def test_all_signatures_distinct():
    # Every candidate must be distinguishable from flow direction + handedness,
    # or the tool could report a false verdict.
    sigs = set()
    for name, R in CANDIDATES.items():
        u, v, hand = signature(R, FX, FY)
        key = (round(np.sign(u) if abs(u) > 1 else 0),
               round(np.sign(v) if abs(v) > 1 else 0), hand)
        assert key not in sigs, f"{name} collides with another candidate"
        sigs.add(key)


def test_flow_magnitude_matches_intrinsics():
    # At 10 m and 1 m/s the streaming rate must equal fx/10 px/s on the u axis.
    u, v, _ = signature(np.eye(3), FX, FY)
    assert math.isclose(abs(u), FX / 10, rel_tol=0.01)
