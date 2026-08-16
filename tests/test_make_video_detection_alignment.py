"""
Bbox/image alignment in tools/make_video.py.

Detections reach the mission log embedded in fsm_tick events whose envelope
time_ns is the LOG time — on real hardware ~0.8 s after the frame was captured
(pipeline latency). Matching a JPEG to the nearest tick and drawing that tick's
detections therefore painted every bbox ~0.8 s behind the image it belonged to.

The fix matches detections by their own capture stamp (time_detected), which is
the exact value used as the JPEG filename stem (detection_simple.py app_callback
and sim_ai frame_ts both stamp the saved image and its detections from the same
variable). These tests build a synthetic mission with a deliberate 810 ms
tick-vs-capture lag and fail if anyone reverts to tick-time matching.

Run with:  python3 -m pytest tests/test_make_video_detection_alignment.py -q
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

try:
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover
    raise unittest.SkipTest("make_video needs cv2/numpy; not installed in this env")

import make_video  # noqa: E402  (tools/make_video.py)

FRAME_INTERVAL_NS = 33_333_333          # one AI frame @ 30 FPS
LAG_NS = 810_000_000                    # measured tick-log vs capture lag (rpi 0139)
T0 = 1_700_000_000_000_000_000          # arbitrary wall-clock ns origin


def _det(td_ns: int, label: str, x: float = 100.0) -> dict:
    """A detection dict shaped like mission_logging._encode_detection output."""
    return {
        "label": label,
        "confidence": 0.9,
        "bbox": [[x, 200.0], [x + 50.0, 260.0]],
        "track_id": None,
        "truth_id": None,
        "time_detected": td_ns,
    }


def _tick(log_ns: int, dets: list[dict], event: str = "fsm_tick") -> dict:
    ev = {
        "time_ns": log_ns,
        "ts": "2026-07-10T00:00:00.000Z",
        "level": "DEBUG",
        "logger": "fsm",
        "event": event,
        "drone_state": {"latitude": 1.0, "longitude": 2.0, "altitude_rel_home": 10.0,
                        "heading": 0.0, "mode": "GUIDED", "arm_state": True,
                        "velocity_x": 0.0, "velocity_y": 0.0, "autonomy_enabled": True},
        "frame": {"width": 640, "height": 640, "detections": dets},
    }
    if event == "fsm_transition":
        ev["state_from"] = "SCAN"
        ev["state_to"] = "GOTO"
    else:
        ev["state"] = "SCAN"
    return ev


def _write_mission(mission_dir: Path, events: list[dict]) -> None:
    header = {
        "time_ns": T0, "ts": "2026-07-10T00:00:00.000Z", "level": "INFO",
        "logger": "main", "event": "mission_start", "schema_version": 2,
        "mission_id": mission_dir.name, "is_sim": False,
    }
    lines = [json.dumps(header)] + [json.dumps(e) for e in events]
    (mission_dir / "mission.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


class LaggedMissionMixin:
    """A mission where every tick logs detections captured LAG_NS earlier.

    Two capture instants: TA and TB = TA + LAG_NS. So the tick logged at
    TA + LAG_NS == TB carries TA's detections — nearest-tick matching for a JPEG
    stamped TB would (wrongly) return TA's boxes.
    """

    TA = T0
    TB = T0 + LAG_NS

    def build(self, mission_dir: Path):
        mission_dir.mkdir(parents=True, exist_ok=True)
        self.dets_a = [_det(self.TA, "sports ball A", x=100.0)]
        self.dets_b = [_det(self.TB, "sports ball B", x=400.0),
                       _det(self.TB, "sports ball B2", x=500.0)]
        events = [
            # dets_a re-logged over several ticks (FSM re-reads the latest frame)
            _tick(self.TA + LAG_NS, self.dets_a),
            _tick(self.TA + LAG_NS + 33_000_000, self.dets_a),
            _tick(self.TA + LAG_NS + 66_000_000, self.dets_a, event="fsm_transition"),
            _tick(self.TB + LAG_NS, self.dets_b),
        ]
        _write_mission(mission_dir, events)
        return make_video.parse_mission(mission_dir)


class TestDetectionIndex(LaggedMissionMixin, unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="skydock_test_vid_")
        self.addCleanup(self.tmp.cleanup)
        self.data = self.build(Path(self.tmp.name) / "0001")

    def test_dedupes_relogged_frames(self):
        # dets_a appears in 3 events (incl. one fsm_transition) but must index once
        self.assertEqual(self.data["det_ts_keys"], [self.TA, self.TB])
        self.assertEqual(len(self.data["det_by_ts"][self.TA]), 1)
        self.assertEqual(len(self.data["det_by_ts"][self.TB]), 2)

    def test_matches_by_capture_time_not_tick_time(self):
        # JPEG stamped TB: nearest tick (log time TB) holds dets_a — the old, wrong
        # answer. Capture-time matching must return dets_b.
        got = make_video.detections_for_frame(self.data, self.TB)
        self.assertEqual([d["label"] for d in got], ["sports ball B", "sports ball B2"])
        got_a = make_video.detections_for_frame(self.data, self.TA)
        self.assertEqual([d["label"] for d in got_a], ["sports ball A"])

    def test_adjacent_unsaved_frame_within_tolerance(self):
        # A JPEG one AI-frame away (unsaved-frame case, SAVE_EVERY_N_FRAMES) still
        # picks up the detections; anything beyond tolerance returns nothing.
        got = make_video.detections_for_frame(self.data, self.TA + FRAME_INTERVAL_NS)
        self.assertEqual([d["label"] for d in got], ["sports ball A"])
        self.assertEqual(
            make_video.detections_for_frame(
                self.data, self.TA + make_video.DET_MATCH_TOL_NS + 1_000_000),
            [])

    def test_empty_index(self):
        self.assertEqual(
            make_video.detections_for_frame(
                {"det_ts_keys": [], "det_by_ts": {}}, self.TA),
            [])


class TestComposeFrameUsesCaptureTime(LaggedMissionMixin, unittest.TestCase):
    """End-to-end through compose_frame with a real JPEG on disk."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="skydock_test_vid_")
        self.addCleanup(self.tmp.cleanup)
        self.mission_dir = Path(self.tmp.name) / "0002"
        self.data = self.build(self.mission_dir)
        frames_dir = self.mission_dir / "frames"
        frames_dir.mkdir()
        self.jpg = frames_dir / f"{self.TB}.jpg"
        cv2.imwrite(str(self.jpg), np.zeros((640, 640, 3), dtype=np.uint8))

    def test_compose_frame_passes_capture_matched_detections(self):
        with mock.patch.object(make_video, "draw_overlay",
                               side_effect=lambda frame, *a, **k: frame) as spy:
            out = make_video.compose_frame(self.jpg, self.TB, self.data, T0, truth=None)
        self.assertIsNotNone(out)
        detections = spy.call_args.args[2]
        self.assertEqual([d["label"] for d in detections],
                         ["sports ball B", "sports ball B2"])
        # And the nearest tick's own frame really would have been the wrong answer,
        # otherwise this test proves nothing about the lag.
        tick = make_video.nearest_by_ts(
            self.data["fsm_ticks_ts"], self.data["fsm_ticks_data"], self.TB)
        self.assertEqual(
            [d["label"] for d in tick["frame"]["detections"]], ["sports ball A"])


if __name__ == "__main__":
    unittest.main()
