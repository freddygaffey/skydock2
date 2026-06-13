"""
Tests for sim_ai.py

Uses the real ai_class, drone_state and constants modules so the tests can
never drift from the real interfaces. Only two modules are stubbed:
telemetry (would pull in pyserial / a live MAVLink connection) and
mission_logging (would write mission.jsonl to disk).
"""

import math
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_tel = types.ModuleType("telemetry")
_tel.telemetry_singlton = None
sys.modules.setdefault("telemetry", _tel)

_ml = types.ModuleType("mission_logging")
_ml.log_event = MagicMock()
sys.modules.setdefault("mission_logging", _ml)

import constants  # noqa: E402
# These tests check geometry, not noise — force deterministic detections.
constants.SIM_AI_ENABLE_IMPERFECTIONS = False

import sim_ai  # noqa: E402  (must come after the telemetry/mission_logging stubs)
from drone_state import DroneStateForHoming  # noqa: E402

# Grab the private helpers for white-box testing
_visible_weed_detections = sim_ai._visible_weed_detections
_vision_params = sim_ai._vision_params

# Image size from sim_ai; intrinsics derived from the drone_state lens model
# (single source of truth — sim_ai no longer has its own camera constants).
IMG_W = sim_ai.NUM_OF_PIX_X
IMG_H = sim_ai.NUM_OF_PIX_Y
CX = IMG_W / 2.0
CY = IMG_H / 2.0
_lens = DroneStateForHoming()
FX = IMG_W / (2 * math.tan(math.radians(_lens.fov_x_deg / 2)))
FY = IMG_H / (2 * math.tan(math.radians(_lens.fov_y_deg / 2)))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _state(lat=0.0, lon=0.0, alt=10.0):
    s = DroneStateForHoming()
    s.latitude = lat
    s.longitude = lon
    s.altitude_rel_home = alt
    return s


def _weed(lat, lon, wid=0):
    return {"id": wid, "lat": lat, "lon": lon}


class TestVisionParams(unittest.TestCase):
    def test_has_expected_top_level_keys(self):
        p = _vision_params(_state())
        self.assertIn("camera", p)
        self.assertIn("sim_ai", p)
        self.assertIn("model", p)

    def test_camera_intrinsics_match_module_constants(self):
        cam = _vision_params(_state())["camera"]
        self.assertAlmostEqual(cam["fx"], FX)
        self.assertAlmostEqual(cam["fy"], FY)
        self.assertEqual(cam["cx"], CX)
        self.assertEqual(cam["cy"], CY)
        self.assertEqual(cam["width_px"], IMG_W)
        self.assertEqual(cam["height_px"], IMG_H)

    def test_sim_ai_fields_present(self):
        sa = _vision_params(_state())["sim_ai"]
        for key in ("fps", "enable_imperfections", "pixel_noise_std_px",
                    "size_noise_std_frac", "miss_prob", "false_pos_prob",
                    "wrong_label_prob", "confidence_mean", "confidence_noise_std",
                    "confidence_min", "confidence_max", "random_seed"):
            self.assertIn(key, sa, f"Missing key: {key}")

    def test_json_serialisable(self):
        import json
        json.dumps(_vision_params(_state()))  # must not raise


class TestVisibleWeedDetectionsEdgeCases(unittest.TestCase):
    def test_none_drone_state_returns_empty(self):
        result = _visible_weed_detections(None, [_weed(0.0, 0.0)])
        self.assertEqual(result, [])

    def test_zero_altitude_returns_empty(self):
        state = _state(alt=0.0)
        result = _visible_weed_detections(state, [_weed(0.0, 0.0)])
        self.assertEqual(result, [])

    def test_negative_altitude_returns_empty(self):
        state = _state(alt=-5.0)
        result = _visible_weed_detections(state, [_weed(0.0, 0.0)])
        self.assertEqual(result, [])

    def test_empty_weed_list_returns_empty(self):
        result = _visible_weed_detections(_state(), [])
        self.assertEqual(result, [])


class TestVisibleWeedDetectionsInView(unittest.TestCase):
    """Weeds directly below the drone should always be detected."""

    def test_weed_directly_below_is_detected(self):
        state = _state(lat=-35.0, lon=149.0, alt=10.0)
        # Weed at exactly the same GPS position → pixel (cx, cy)
        dets = _visible_weed_detections(state, [_weed(-35.0, 149.0)])
        self.assertEqual(len(dets), 1)

    def test_detection_label_is_sports_ball(self):
        state = _state(lat=-35.0, lon=149.0, alt=10.0)
        dets = _visible_weed_detections(state, [_weed(-35.0, 149.0)])
        self.assertEqual(dets[0].label, "sports ball")

    def test_detection_confidence_is_0_9(self):
        state = _state(lat=-35.0, lon=149.0, alt=10.0)
        dets = _visible_weed_detections(state, [_weed(-35.0, 149.0)])
        self.assertAlmostEqual(dets[0].confidence, 0.9)

    def test_multiple_weeds_below_all_detected(self):
        lat, lon = -35.0, 149.0
        state = _state(lat=lat, lon=lon, alt=10.0)
        # Three weeds within a metre of the drone, all should be in frame
        weeds = [
            _weed(lat, lon, 0),
            _weed(lat + 1e-5, lon, 1),
            _weed(lat, lon + 1e-5, 2),
        ]
        dets = _visible_weed_detections(state, weeds)
        self.assertEqual(len(dets), 3)


class TestVisibleWeedDetectionsOutOfView(unittest.TestCase):
    """Weeds far away (beyond ground footprint) must not appear."""

    def test_weed_far_away_not_detected(self):
        state = _state(lat=-35.0, lon=149.0, alt=10.0)
        # 1 km north – well outside any reasonable FOV at 10 m altitude
        far_lat = -35.0 + (1000.0 / 111_320.0)
        dets = _visible_weed_detections(state, [_weed(far_lat, 149.0)])
        self.assertEqual(dets, [])

    def test_mixed_weeds_only_visible_returned(self):
        lat, lon = -35.0, 149.0
        state = _state(lat=lat, lon=lon, alt=10.0)
        far_lat = lat + (500.0 / 111_320.0)
        weeds = [_weed(lat, lon, 0), _weed(far_lat, lon, 1)]
        dets = _visible_weed_detections(state, weeds)
        self.assertEqual(len(dets), 1)


class TestVisibleWeedDetectionsBboxSanity(unittest.TestCase):
    """Bounding boxes must be valid and within image bounds."""

    def _det_for_weed_below(self, alt=10.0):
        state = _state(lat=-35.0, lon=149.0, alt=alt)
        dets = _visible_weed_detections(state, [_weed(-35.0, 149.0)])
        self.assertEqual(len(dets), 1)
        return dets[0]

    def test_bbox_has_two_corners(self):
        d = self._det_for_weed_below()
        self.assertEqual(len(d.bbox), 2)

    def test_bbox_within_image_bounds(self):
        d = self._det_for_weed_below()
        (x_min, y_min), (x_max, y_max) = d.bbox
        self.assertGreaterEqual(x_min, 0)
        self.assertGreaterEqual(y_min, 0)
        self.assertLessEqual(x_max, IMG_W)
        self.assertLessEqual(y_max, IMG_H)

    def test_bbox_x_min_lt_x_max(self):
        d = self._det_for_weed_below()
        (x_min, _), (x_max, _) = d.bbox
        self.assertLess(x_min, x_max)

    def test_bbox_y_min_lt_y_max(self):
        d = self._det_for_weed_below()
        (_, y_min), (_, y_max) = d.bbox
        self.assertLess(y_min, y_max)

    def test_weed_directly_below_projects_near_image_centre(self):
        """A weed directly under the drone should land close to the principal point."""
        d = self._det_for_weed_below()
        (x_min, y_min), (x_max, y_max) = d.bbox
        cx = (x_min + x_max) / 2.0
        cy = (y_min + y_max) / 2.0
        # Allow ±5 px of centre
        self.assertAlmostEqual(cx, CX, delta=5.0)
        self.assertAlmostEqual(cy, CY, delta=5.0)

    def test_bbox_size_increases_at_lower_altitude(self):
        """Closer to the ground → weed appears larger in the frame."""
        d_high = self._det_for_weed_below(alt=20.0)
        d_low  = self._det_for_weed_below(alt=5.0)

        (x_min_h, y_min_h), (x_max_h, y_max_h) = d_high.bbox
        (x_min_l, y_min_l), (x_max_l, y_max_l) = d_low.bbox

        w_high = x_max_h - x_min_h
        w_low  = x_max_l - x_min_l
        self.assertGreater(w_low, w_high)

    def test_bbox_minimum_size_enforced(self):
        """Even at extreme altitude the bbox should be at least min_px × min_px."""
        state = _state(lat=-35.0, lon=149.0, alt=1000.0)
        dets = _visible_weed_detections(state, [_weed(-35.0, 149.0)])
        if not dets:
            self.skipTest("Weed not in FOV at extreme altitude – skip size check")
        (x_min, y_min), (x_max, y_max) = dets[0].bbox
        self.assertGreaterEqual(x_max - x_min, 8.0 - 1)   # bbox clamped to min 8 px
        self.assertGreaterEqual(y_max - y_min, 8.0 - 1)


class TestRunSimAiStartsThread(unittest.TestCase):
    """run_sim_ai should launch a background daemon thread."""

    def test_thread_is_started(self):
        import threading
        started_threads = []
        original_thread = threading.Thread

        def capture_thread(*args, **kwargs):
            t = original_thread(*args, **kwargs)
            started_threads.append(t)
            # This test only verifies a daemon thread is created. Don't actually
            # run the infinite _loop — it would leak and tick forever against the
            # shared (mocked) telemetry_singlton, raising thread exceptions.
            t.start = lambda: None
            return t

        with patch("threading.Thread", side_effect=capture_thread):
            sim_ai.run_sim_ai([])

        self.assertGreater(len(started_threads), 0, "Expected threading.Thread to be called")

    def test_thread_is_daemon(self):
        import threading
        created = []
        original_thread = threading.Thread

        def capture_thread(*args, **kwargs):
            t = original_thread(*args, **kwargs)
            created.append(t)
            # Verify the daemon flag without running the infinite _loop (see above).
            t.start = lambda: None
            return t

        with patch("threading.Thread", side_effect=capture_thread):
            sim_ai.run_sim_ai([])

        self.assertTrue(all(t.daemon for t in created), "Background thread should be a daemon")


if __name__ == "__main__":
    unittest.main()
