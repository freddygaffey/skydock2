from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from factory import create_app


@pytest.fixture()
def app_with_missions():
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


def test_summary_route(app_with_missions):
    client = app_with_missions.test_client()
    r = client.get("/missions/0001/summary")
    assert r.status_code == 200
    data = r.get_json()
    assert data["insights"]["jsonl_lines"] >= 1
