"""POST /missions/<id>/generate_video — job launch + the obfuscate_gps setting.

The endpoint spawns tools/make_video.py in the background; these tests fake the
subprocess and ffmpeg check and assert the exact command line, so a regression
in flag plumbing (e.g. the privacy flag silently dropped) fails here rather
than surfacing as a video that leaks the field's GPS.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import mock

import pytest

import routes_api
from factory import create_app


class _FakeProc:
    pid = 4242

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


@pytest.fixture()
def app_with_video_mission():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mid = root / "0001"
        frames = mid / "frames"
        frames.mkdir(parents=True)
        fix = Path(__file__).resolve().parent / "fixtures" / "minimal_mission.jsonl"
        (mid / "mission.jsonl").write_text(fix.read_text(encoding="utf-8"), encoding="utf-8")
        (frames / "1704067204000000000.jpg").write_bytes(b"\xff\xd8\xff\xd9")
        app = create_app()
        app.config["MISSIONS_ROOT"] = root
        app.config["RPI_MISSIONS_ROOT"] = root
        app.config["SIM_DATA_ROOT"] = root
        app.config["TESTING"] = True
        yield app


def _post_generate(app, query: str) -> tuple[dict, list[str]]:
    """POST generate_video with subprocess+ffmpeg faked; return (json, popen argv)."""
    client = app.test_client()
    with mock.patch.object(routes_api, "_ffmpeg_available_for_video", return_value=True), \
         mock.patch.object(routes_api.subprocess, "Popen",
                           return_value=_FakeProc()) as popen:
        r = client.post(f"/missions/0001/generate_video?src=sim{query}")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True, data
    assert popen.call_count == 1
    argv = popen.call_args.args[0]
    assert isinstance(argv, list) and all(isinstance(a, str) for a in argv)
    return data, argv


def test_generate_video_default_no_obfuscation(app_with_video_mission):
    data, argv = _post_generate(app_with_video_mission, "")
    assert "--obfuscate-gps" not in argv
    assert data["obfuscate_gps"] is False
    assert argv[-1].endswith("0001")            # mission dir is the target
    assert any(a.endswith("make_video.py") for a in argv)


@pytest.mark.parametrize("val", ["1", "true", "yes", "on"])
def test_generate_video_obfuscation_on(app_with_video_mission, val):
    data, argv = _post_generate(app_with_video_mission, f"&obfuscate_gps={val}")
    assert "--obfuscate-gps" in argv
    assert data["obfuscate_gps"] is True


def test_generate_video_obfuscation_falsy_values_off(app_with_video_mission):
    for val in ["0", "false", ""]:
        _, argv = _post_generate(app_with_video_mission, f"&obfuscate_gps={val}")
        assert "--obfuscate-gps" not in argv


def test_generate_video_logs_full_command(app_with_video_mission):
    """generate_video.log must record the real argv (incl. the privacy flag)."""
    _post_generate(app_with_video_mission, "&obfuscate_gps=1")
    root = app_with_video_mission.config["MISSIONS_ROOT"]
    log_text = (root / "0001" / "generate_video.log").read_text(encoding="utf-8")
    assert "--obfuscate-gps" in log_text
