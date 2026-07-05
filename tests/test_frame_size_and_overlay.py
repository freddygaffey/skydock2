"""Tests for Frame pixel-size metadata and the live-stream overlay scaling.

Covers the July 2026 homing-blind bug fixes (docs/Bug Notes.md):
- Frame carries the actual source-image size instead of a hardcoded 1280.
- The real AI callback (hailo detection_simple.py) must use the CURRENT
  telemetry singleton name, fix frame timestamps against pipeline base time,
  and stamp Frames with the caps size. It cannot be imported on dev machines
  (gi/hailo), so those are source-contract checks like test_log_contract.py.
- server.py overlay text scales with the image and bbox scaling tolerates
  frames of unknown size.

Run with:  python -m pytest tests/test_frame_size_and_overlay.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

REPO = Path(__file__).resolve().parent.parent
CALLBACK_SRC = (REPO / "hailo-rpi5-examples/basic_pipelines/detection_simple.py").read_text()


# ---------------------------------------------------------------------------
# Frame size metadata
# ---------------------------------------------------------------------------

def test_frame_stores_given_size():
    from ai_class import Frame
    f = Frame([], width=640, height=480)
    assert f.width == 640
    assert f.height == 480


def test_frame_size_defaults_to_unknown():
    # No more hardcoded 1280x1280: unknown means "assume same-size", never a
    # silently wrong scale factor.
    from ai_class import Frame
    f = Frame([])
    assert f.width is None
    assert f.height is None


def test_sim_ai_stamps_frames_with_its_pixel_space():
    src = (REPO / "sim_ai.py").read_text()
    assert "width=NUM_OF_PIX_X" in src and "height=NUM_OF_PIX_Y" in src


# ---------------------------------------------------------------------------
# Real-callback source contract (regression guards for the homing-blind bug)
# ---------------------------------------------------------------------------

def test_callback_does_not_use_stale_singleton_name():
    # The June 2026 rename left getattr(telemetry, "telemetry_singlton", None)
    # returning None forever -> resolution never reached drone_state.
    assert "telemetry_singlton" not in CALLBACK_SRC
    assert 'getattr(telemetry, "telemetry_singleton"' in CALLBACK_SRC


def test_callback_fails_loudly_when_telemetry_missing():
    assert "ERROR ai_callback: telemetry.telemetry_singleton is missing" in CALLBACK_SRC


def test_callback_stamps_frame_with_caps_size():
    assert "Frame([], width=width, height=height)" in CALLBACK_SRC


def test_callback_timestamps_use_pipeline_base_time():
    # buffer.pts is measured against running time (clock - base_time); using the
    # raw clock skewed frame timestamps by the pipeline start time (~606 s).
    assert "get_base_time()" in CALLBACK_SRC
    assert "(pipeline_now - base_time) - buffer.pts" in CALLBACK_SRC


# ---------------------------------------------------------------------------
# server.py overlay scaling
# ---------------------------------------------------------------------------

def test_overlay_font_scales_with_image_and_has_floor():
    import server
    s640, t640, l640 = server._overlay_font(640)
    s1280, t1280, l1280 = server._overlay_font(1280)
    s64, _, l64 = server._overlay_font(64)
    # bigger image -> proportionally bigger text
    assert abs(s1280 / s640 - 2.0) < 1e-6
    assert l1280 > l640 > 0
    assert t1280 >= t640 >= 1
    # tiny images still get readable text (10 px cap floor)
    assert s64 * 22 >= 10.0


def _serve_frame(tmp_path, fsm, size):
    import cv2
    import numpy as np
    import server
    from mission_logging import configure_mission_dir

    (tmp_path / "frames").mkdir(exist_ok=True)
    cv2.imwrite(str(tmp_path / "frames" / "latest.jpg"),
                np.zeros((size, size, 3), dtype=np.uint8))
    configure_mission_dir(tmp_path)
    app = server.create_app(fsm=fsm)
    app.config["TESTING"] = True
    return app.test_client().get("/frame.jpg")


class _Det:
    label = "sports ball"
    confidence = 0.9
    bbox = [(100.0, 100.0), (200.0, 200.0)]


class _Fsm:
    current_state = "HOMING"

    def __init__(self, frame):
        self.frame = frame
        self.drone_state = None


def test_frame_endpoint_renders_any_image_size(tmp_path):
    from ai_class import Frame
    for size in (320, 1280):
        r = _serve_frame(tmp_path, _Fsm(Frame([_Det()], width=640, height=640)), size)
        assert r.status_code == 200, size
        assert r.mimetype == "image/jpeg"


def test_frame_endpoint_tolerates_unknown_frame_size(tmp_path):
    # width/height None must fall back to 1:1 scaling, not divide-by-None.
    from ai_class import Frame
    r = _serve_frame(tmp_path, _Fsm(Frame([_Det()])), 640)
    assert r.status_code == 200
    assert r.mimetype == "image/jpeg"
