"""Smoke tests for HTML routes (mission-scoped nav)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from factory import create_app


@pytest.fixture()
def app_ctx():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mid = root / "0001"
        mid.mkdir()
        fix = Path(__file__).resolve().parent / "fixtures" / "minimal_mission.jsonl"
        (mid / "mission.jsonl").write_text(fix.read_text(encoding="utf-8"), encoding="utf-8")
        app = create_app()
        app.config["MISSIONS_ROOT"] = root
        app.config["RPI_MISSIONS_ROOT"] = root
        app.config["SIM_DATA_ROOT"] = root
        app.config["TESTING"] = True
        yield app


def test_root_redirects_to_missions_list(app_ctx):
    c = app_ctx.test_client()
    r = c.get("/", follow_redirects=False)
    assert r.status_code == 302
    assert "/missions" in r.headers.get("Location", "")


def test_mission_weed_marking_scoped(app_ctx):
    c = app_ctx.test_client()
    r = c.get("/missions/0001/weed-marking")
    assert r.status_code == 200
    assert b"Weed marking" in r.data
    assert b"Mission 0001" in r.data


def test_build_index_post(app_ctx):
    c = app_ctx.test_client()
    r = c.post("/missions/0001/index?src=sim")
    assert r.status_code == 200
    data = r.get_json()
    assert data.get("ok") is True
    assert "index_path" in data
