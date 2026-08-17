"""The kind-filtered endpoints (/fsm, /weeds, /spray) must stay exact while being cheap.

These used to json-decode every line of the log on every request — ~5 s per call on an
850 MB real mission, repeated for each of the several requests a dashboard load fires. They
now read only the matching rows out of the sqlite sidecar and memoise per log revision, so
these tests pin both the contents and the invalidation.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from factory import create_app

_KIND_ROWS = [
    {"event": "mission_start", "ts": "2024-01-01T00:00:00.000Z", "schema_version": 2},
    {"event": "telemetry_sample", "ts": "2024-01-01T00:00:01.000Z",
     "drone_state": {"latitude": -35.0, "longitude": 149.0, "altitude_rel_home": 5.0}},
    {"event": "fsm_transition", "ts": "2024-01-01T00:00:02.000Z",
     "state_from": "OVERRIDE", "state_to": "SCAN"},
    {"event": "weed_detected", "ts": "2024-01-01T00:00:03.000Z",
     "weed": {"id": 0, "lat": -35.0, "lon": 149.0}},
    {"event": "spray_attempt", "ts": "2024-01-01T00:00:04.000Z", "weed_id": 0},
    {"event": "db_weed_sprayed", "ts": "2024-01-01T00:00:05.000Z", "weed_id": 0},
    {"event": "move_command", "ts": "2024-01-01T00:00:06.000Z"},
    {"event": "fsm_transition", "ts": "2024-01-01T00:00:07.000Z",
     "state_from": "SCAN", "state_to": "GOTO"},
]


def _write(root: Path, rows) -> None:
    d = root / "0001"
    d.mkdir(parents=True, exist_ok=True)
    (d / "mission.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


@pytest.fixture()
def app_ctx():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write(root, _KIND_ROWS)
        app = create_app()
        app.config.update(MISSIONS_ROOT=root, RPI_MISSIONS_ROOT=root, SIM_DATA_ROOT=root,
                          TESTING=True)
        app.config["_ROOT"] = root
        yield app


def test_fsm_returns_exactly_the_transitions(app_ctx):
    rows = app_ctx.test_client().get("/missions/0001/fsm?src=sim").get_json()
    assert rows == [r for r in _KIND_ROWS if r["event"] == "fsm_transition"]


def test_weeds_returns_the_weed_and_spray_kinds_in_log_order(app_ctx):
    kinds = {"weed_detected", "db_weed_sprayed", "spray_attempt", "spray_miss", "spray_ready"}
    rows = app_ctx.test_client().get("/missions/0001/weeds?src=sim").get_json()
    assert rows == [r for r in _KIND_ROWS if r["event"] in kinds]


def test_spray_returns_the_spray_kinds_in_log_order(app_ctx):
    kinds = {"db_weed_sprayed", "spray_attempt", "spray_miss", "spray_ready", "spray_skipped"}
    rows = app_ctx.test_client().get("/missions/0001/spray?src=sim").get_json()
    assert rows == [r for r in _KIND_ROWS if r["event"] in kinds]


def test_unrelated_kinds_are_never_included(app_ctx):
    c = app_ctx.test_client()
    for url in ("/missions/0001/fsm?src=sim", "/missions/0001/weeds?src=sim",
                "/missions/0001/spray?src=sim"):
        rows = c.get(url).get_json()
        assert all(r["event"] not in ("telemetry_sample", "move_command", "mission_start")
                   for r in rows), url


def test_result_is_recomputed_after_the_log_changes(app_ctx):
    """Per-revision memoisation must not serve stale rows for a growing (live) log."""
    c = app_ctx.test_client()
    assert len(c.get("/missions/0001/fsm?src=sim").get_json()) == 2

    root: Path = app_ctx.config["_ROOT"]
    _write(root, _KIND_ROWS + [
        {"event": "fsm_transition", "ts": "2024-01-01T00:00:09.000Z",
         "state_from": "GOTO", "state_to": "SPRAY"},
    ])
    assert len(c.get("/missions/0001/fsm?src=sim").get_json()) == 3


def test_sim_vision_none_result_is_still_correct(app_ctx):
    """Real missions never emit sim_vision_params; the (cached) answer must stay null."""
    c = app_ctx.test_client()
    assert c.get("/missions/0001/sim_vision?src=sim").get_json() is None
    assert c.get("/missions/0001/sim_vision?src=sim").get_json() is None
