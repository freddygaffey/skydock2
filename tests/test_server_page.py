import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server


def _client():
    app = server.create_app(fsm=None)
    app.config["TESTING"] = True
    return app.test_client()


def test_index_serves_viewer_page():
    r = _client().get("/")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    # the JS loop must poll the frame endpoint with a cache-buster
    assert "/frame.jpg?t=" in html
    assert "setTimeout(tick, 1000 / targetFps())" in html


def test_fps_controls_allow_quarter_fps():
    html = _client().get("/").get_data(as_text=True)
    # both the number box and the slider go down to 0.25 fps, synced
    assert 'id="fpsnum" type="number" min="0.25"' in html
    assert 'id="fps" type="range" min="0.25"' in html
    assert "slider.value = num.value" in html
    assert "num.value = slider.value" in html


def test_frame_endpoint_exists():
    app = server.create_app(fsm=None)
    rules = {r.rule for r in app.url_map.iter_rules()}
    assert "/frame.jpg" in rules


class _FakeDroneState:
    mode = "GUIDED"
    altitude_rel_home = 9.7
    velocity_x = 1.0
    velocity_y = 0.0
    heading = 90.0


class _FakeDetection:
    label = "sports ball"
    confidence = 0.9
    bbox = [(100.0, 100.0), (200.0, 200.0)]


class _FakeFrame:
    width = 640
    height = 640
    detection = [_FakeDetection()]


class _FakeFsm:
    current_state = "SCAN"
    frame = _FakeFrame()
    drone_state = _FakeDroneState()


def test_frame_endpoint_reads_frame_and_state_from_fsm(tmp_path):
    import cv2
    import numpy as np
    from mission_logging import configure_mission_dir

    (tmp_path / "frames").mkdir()
    cv2.imwrite(str(tmp_path / "frames" / "latest.jpg"),
                np.zeros((640, 640, 3), dtype=np.uint8))
    configure_mission_dir(tmp_path)

    app = server.create_app(fsm=_FakeFsm())
    app.config["TESTING"] = True
    r = app.test_client().get("/frame.jpg")
    assert r.status_code == 200
    assert r.mimetype == "image/jpeg"
    assert len(r.data) > 500  # a real encoded jpeg, not an error string


def _make_mission(root, name, is_sim):
    d = root / name
    (d / "frames").mkdir(parents=True)
    (d / "frames" / "latest.jpg").write_bytes(b"jpg")
    (d / "mission.jsonl").write_text(
        json.dumps({"event": "mission_start", "is_sim": is_sim}) + "\n")
    return d


def test_find_latest_mission_prefers_real_over_newer_sim(tmp_path):
    real = _make_mission(tmp_path, "0001", is_sim=False)
    _make_mission(tmp_path, "0002", is_sim=True)
    assert server.find_latest_mission_with_frames(tmp_path) == real


def test_find_latest_mission_falls_back_to_sim(tmp_path):
    _make_mission(tmp_path, "0001", is_sim=True)
    sim2 = _make_mission(tmp_path, "0002", is_sim=True)
    assert server.find_latest_mission_with_frames(tmp_path) == sim2


def test_find_latest_mission_none_when_empty(tmp_path):
    assert server.find_latest_mission_with_frames(tmp_path) is None
