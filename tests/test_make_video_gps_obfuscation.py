"""
GPS obfuscation in tools/make_video.py (--obfuscate-gps).

Shared mission videos must be able to hide the field's location: with the flag
on, the overlay shows lat/lon rounded to GPS_OBFUSCATE_DEG degrees (2° ≈
±100–220 km) and the full-precision coordinates must appear NOWHERE in the
rendered text. These tests capture every cv2.putText string draw_overlay emits
and fail if a precise coordinate leaks, plus check the flag threads through
compose_frame.

Run with:  python3 -m pytest tests/test_make_video_gps_obfuscation.py -q
"""

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

import make_video  # noqa: E402

# A recognisably real location (Sydney-ish) with plenty of decimals.
LAT, LON = -33.8688197, 151.2092955

DRONE_STATE = {
    "latitude": LAT, "longitude": LON, "altitude_rel_home": 10.0,
    "heading": 90.0, "mode": "GUIDED", "arm_state": True,
    "velocity_x": 1.0, "velocity_y": 0.0, "autonomy_enabled": True,
}


def _overlay_texts(obfuscate_gps: bool) -> list[str]:
    """All strings draw_overlay paints, with putText intercepted."""
    frame = np.zeros((640, 640, 3), dtype=np.uint8)
    texts: list[str] = []
    real_puttext = cv2.putText

    def spy(img, text, *a, **k):
        texts.append(text)
        return real_puttext(img, text, *a, **k)

    with mock.patch.object(make_video.cv2, "putText", side_effect=spy):
        make_video.draw_overlay(frame, dict(DRONE_STATE), [], "SCAN", 12.0,
                                accuracy=None, obfuscate_gps=obfuscate_gps)
    return texts


class TestFormatLatLon(unittest.TestCase):
    def test_precise_by_default(self):
        s = make_video.format_latlon(LAT, LON, obfuscate=False)
        self.assertIn(f"{LAT:.7f}", s)
        self.assertIn(f"{LON:.7f}", s)

    def test_obfuscated_rounds_to_quantum(self):
        s = make_video.format_latlon(LAT, LON, obfuscate=True)
        self.assertEqual(s, "Lat: ~-34  Lon: ~152  (GPS hidden)")

    def test_obfuscated_error_bounded_but_nonzero_precision_loss(self):
        # Rounding to the quantum: shown value within q/2 of truth (so the video is
        # still honest about the rough region) but never finer than the quantum.
        q = make_video.GPS_OBFUSCATE_DEG
        self.assertGreaterEqual(q, 1.0)  # ≥ ~±55 km; 2.0 gives the requested ±100–200 km
        for deg in (-89.9, -33.8688197, -0.4, 0.0, 0.9999, 51.5, 151.2092955, 179.9):
            shown = round(deg / q) * q
            self.assertLessEqual(abs(shown - deg), q / 2 + 1e-9)
            self.assertEqual(shown % 1.0, 0.0)  # whole degrees only — no decimals leak

    def test_no_decimal_point_in_obfuscated_output(self):
        for lat, lon in ((-33.8688197, 151.2092955), (0.49, -0.51), (89.9, -179.9)):
            s = make_video.format_latlon(lat, lon, obfuscate=True)
            self.assertNotIn(".", s)


class TestDrawOverlayObfuscation(unittest.TestCase):
    def test_precise_coords_shown_by_default(self):
        joined = "\n".join(_overlay_texts(obfuscate_gps=False))
        self.assertIn(f"{LAT:.7f}", joined)
        self.assertIn(f"{LON:.7f}", joined)

    def test_obfuscation_removes_precise_coords_everywhere(self):
        texts = _overlay_texts(obfuscate_gps=True)
        joined = "\n".join(texts)
        # No fragment of the precise coordinates anywhere in the overlay text —
        # even a few leading decimals would localise the field to metres.
        for leak in (f"{LAT:.7f}", f"{LON:.7f}", "33.86", "151.20", "-33.8", "151.2"):
            self.assertNotIn(leak, joined)
        self.assertIn("Lat: ~-34  Lon: ~152  (GPS hidden)", joined)
        # Non-locating telemetry still shown.
        self.assertTrue(any("Alt:" in t for t in texts))


class TestComposeFrameThreadsFlag(unittest.TestCase):
    def test_compose_frame_passes_obfuscate_to_draw_overlay(self):
        data = {
            "fsm_ticks_ts": [1], "fsm_ticks_data": [{"drone_state": dict(DRONE_STATE)}],
            "fsm_trans_ts": [], "fsm_trans_state": [],
            "weed_events_ts": [], "weed_events_data": [],
            "det_ts_keys": [], "det_by_ts": {},
        }
        with tempfile.TemporaryDirectory() as td:
            jpg = Path(td) / "1.jpg"
            cv2.imwrite(str(jpg), np.zeros((64, 64, 3), dtype=np.uint8))
            for flag in (False, True):
                with mock.patch.object(make_video, "draw_overlay",
                                       side_effect=lambda frame, *a, **k: frame) as spy:
                    out = make_video.compose_frame(jpg, 1, data, 0, truth=None,
                                                   obfuscate_gps=flag)
                self.assertIsNotNone(out)
                self.assertEqual(spy.call_args.kwargs.get("obfuscate_gps"), flag)


class TestBuildersThreadFlag(unittest.TestCase):
    """A builder that forgets to pass obfuscate_gps to compose_frame silently
    reverts to precise coordinates — catch that at the call-site level."""

    def _mission(self, td: Path) -> Path:
        mdir = td / "0001"
        (mdir / "frames").mkdir(parents=True)
        header = ('{"time_ns": 1, "ts": "2026-07-10T00:00:00.000Z", "level": "INFO", '
                  '"logger": "main", "event": "mission_start", "schema_version": 2, '
                  '"mission_id": "0001", "is_sim": false}')
        (mdir / "mission.jsonl").write_text(header + "\n", encoding="utf-8")
        for stem in (1_000_000_000, 2_000_000_000):
            cv2.imwrite(str(mdir / "frames" / f"{stem}.jpg"),
                        np.zeros((64, 64, 3), dtype=np.uint8))
        return mdir

    def test_realtime_builder_passes_flag(self):
        with tempfile.TemporaryDirectory() as td:
            mdir = self._mission(Path(td))
            seen: list[bool] = []

            def fake_compose(img_path, ts_ns, data, start_ns, truth, obfuscate_gps=False):
                seen.append(obfuscate_gps)
                return np.zeros((64, 64, 3), dtype=np.uint8)

            # Stop before ffmpeg: fail the run right after all frames composed.
            with mock.patch.object(make_video, "compose_frame", side_effect=fake_compose), \
                 mock.patch.object(make_video, "resolve_ffmpeg_exe", return_value="ffmpeg"), \
                 mock.patch.object(make_video.subprocess, "run",
                                   side_effect=RuntimeError("stop-before-encode")), \
                 self.assertRaises(RuntimeError):
                make_video.build_video_realtime(mdir, mdir / "out.mp4", obfuscate_gps=True)
            self.assertTrue(seen and all(seen))

    def test_fixed_fps_builder_passes_flag(self):
        with tempfile.TemporaryDirectory() as td:
            mdir = self._mission(Path(td))
            seen: list[bool] = []

            def fake_compose(img_path, ts_ns, data, start_ns, truth, obfuscate_gps=False):
                seen.append(obfuscate_gps)
                return np.zeros((64, 64, 3), dtype=np.uint8)

            with mock.patch.object(make_video, "compose_frame", side_effect=fake_compose), \
                 mock.patch.object(make_video, "transcode_h264_for_web", return_value=True), \
                 mock.patch.object(make_video, "_publish_video"):
                make_video.build_video_fixed_fps(mdir, mdir / "out.mp4", 10.0,
                                                 obfuscate_gps=True)
            self.assertTrue(seen and all(seen))


if __name__ == "__main__":
    unittest.main()
