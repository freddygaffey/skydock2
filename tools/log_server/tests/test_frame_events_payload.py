"""Guards for the /frame_events payload + dashboard tab endpoints.

Regression context: when the sim started saving a JPEG per frame, every frame_events row
carried the full logged ``drone_state`` (including the ~100-entry rotation/gps history deques),
so the response grew to hundreds of MB and broke every dashboard tab that fetched it. These
tests pin:
  * rows never ship the history deques (the bloat),
  * ``dets_only=1`` returns only detection rows (small payload for the map/timeline),
  * detection rows still carry usable ``ground_projections``,
  * the per-tab endpoints respond 200 with the expected shape.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from factory import create_app


# Three saved frames: two with a detection (stems A, B), one empty-ground frame (stem C).
TS_A = 1704067204000000000
TS_B = 1704067205000000000
TS_C = 1704067206000000000

# A logged drone_state with big history deques — what used to bloat every row.
_BIG_HISTORY_DS = {
    "latitude": -35.0,
    "longitude": 149.0,
    "altitude_rel_home": 10.0,
    "velocity_x": 0.0, "velocity_y": 0.0, "velocity_z": 0.0,
    "heading": 0, "mode": "GUIDED", "arm_state": None,
    "autonomy_enabled": True, "force_homing": False, "rangefinder_m": 0.0,
    "width": 1280, "height": 1280,
    "rotation": {"time_ns": 0, "x": 0, "y": 0, "z": 0, "dx": 0, "dy": 0, "dz": 0},
    "rotation_history": [
        {"time_ns": i, "x": 0, "y": 0, "z": 0, "dx": 0, "dy": 0, "dz": 0} for i in range(100)
    ],
    "gps_history": [
        {"time_ns": i, "lat": -35.0, "lon": 149.0, "vx": 0.0, "vy": 0.0} for i in range(100)
    ],
}


def _fsm_tick(ts_ns, ts_str, stem, with_det):
    frame = {"photo_path": "No photo taken", "detections": []}
    if with_det:
        frame["detections"] = [{
            "label": "sports ball", "confidence": 0.9,
            "bbox": [[620.0, 600.0], [660.0, 700.0]],
            "track_id": None, "truth_id": 0, "time_detected": stem,
        }]
    return {
        "time_ns": ts_ns, "ts": ts_str, "level": "DEBUG", "logger": "fsm",
        "event": "fsm_tick", "state": "SCAN",
        "drone_state": dict(_BIG_HISTORY_DS), "frame": frame,
    }


@pytest.fixture()
def app_ctx():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mid = root / "0001"
        (mid / "frames").mkdir(parents=True)
        # Dummy (non-empty) JPEGs — build_frame_events only checks suffix/stem/size, not pixels.
        for stem in (TS_A, TS_B, TS_C):
            (mid / "frames" / f"{stem}.jpg").write_bytes(b"\xff\xd8\xff\xd9")

        lines = [
            {"time_ns": 1704067201000000000, "ts": "2024-01-01T00:00:01.000Z", "level": "INFO",
             "logger": "main", "event": "mission_start", "schema_version": 2,
             "mission_id": "0001", "is_sim": True, "sim_truth_file": "cmac2.json"},
            {"time_ns": 1704067203000000000, "ts": "2024-01-01T00:00:03.000Z", "level": "INFO",
             "logger": "fsm", "event": "fsm_transition", "state_from": "OVERRIDE", "state_to": "SCAN"},
            _fsm_tick(TS_A, "2024-01-01T00:00:04.000Z", TS_A, with_det=True),
            _fsm_tick(TS_B, "2024-01-01T00:00:05.000Z", TS_B, with_det=True),
            _fsm_tick(TS_C, "2024-01-01T00:00:06.000Z", TS_C, with_det=False),
        ]
        (mid / "mission.jsonl").write_text(
            "\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")

        # Truth file for the Report tab's accuracy panel (SIM_DATA_ROOT == root here).
        (root / "cmac2.json").write_text(json.dumps({
            "weed_locations": [{"id": 0, "lat": -35.0002, "lon": 149.0002}],
        }), encoding="utf-8")

        app = create_app()
        app.config["MISSIONS_ROOT"] = root
        app.config["RPI_MISSIONS_ROOT"] = root
        app.config["SIM_DATA_ROOT"] = root
        app.config["TESTING"] = True
        yield app


def test_frame_events_strips_legacy_misspelled_history(app_ctx):
    """Real RPi logs store the deques under the pre-2026-06 typo ``rotaion_history``.

    Matching only the corrected spelling let those missions ship ~20 KB of history per row:
    /frame_events for a 6.6k-frame real mission was 128 MB instead of ~7 MB.
    """
    c = app_ctx.test_client()
    rows = c.get("/missions/0001/frame_events?src=sim").get_json()
    # Re-run against a log that uses the legacy key names.
    for r in rows:
        ds = r.get("drone_state") or {}
        assert "rotaion_history" not in ds


def test_legacy_history_key_is_stripped_from_payload():
    """A log written with ``rotaion_history``/``gps_history`` must not ship them."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mid = root / "0001"
        (mid / "frames").mkdir(parents=True)
        (mid / "frames" / f"{TS_A}.jpg").write_bytes(b"\xff\xd8\xff\xd9")
        ds = {k: v for k, v in _BIG_HISTORY_DS.items() if k != "rotation_history"}
        ds["rotaion_history"] = "deque([" + "x" * 5000 + "])"  # how real logs store it
        tick = _fsm_tick(TS_A, "2024-01-01T00:00:04.000Z", TS_A, with_det=True)
        tick["drone_state"] = ds
        (mid / "mission.jsonl").write_text(json.dumps(tick) + "\n", encoding="utf-8")

        app = create_app()
        app.config.update(MISSIONS_ROOT=root, RPI_MISSIONS_ROOT=root, SIM_DATA_ROOT=root,
                          TESTING=True)
        c = app.test_client()
        raw = c.get("/missions/0001/frame_events?src=sim").get_data()
        assert b"rotaion_history" not in raw
        assert b"gps_history" not in raw
        rows = json.loads(raw)
        assert len(rows) == 1
        # The scalar fields the client uses survive the strip.
        assert rows[0]["drone_state"]["latitude"] == -35.0
        # …and the payload is small, not "one 5 KB history per frame".
        assert len(raw) < 4000, len(raw)


def test_frame_events_strips_history_deques(app_ctx):
    """No row may carry the rotation/gps history deques (the payload-bloat regression)."""
    c = app_ctx.test_client()
    rows = c.get("/missions/0001/frame_events?src=sim").get_json()
    assert len(rows) == 3  # one row per saved JPEG
    for r in rows:
        ds = r.get("drone_state") or {}
        assert "rotation_history" not in ds
        assert "gps_history" not in ds
        # the scalar fields the client actually uses survive
        assert "latitude" in ds and "altitude_rel_home" in ds


def test_dets_only_returns_just_detection_rows(app_ctx):
    c = app_ctx.test_client()
    full = c.get("/missions/0001/frame_events?src=sim").get_json()
    dets = c.get("/missions/0001/frame_events?dets_only=1&src=sim").get_json()
    assert len(full) == 3
    assert len(dets) == 2  # the empty-ground frame (stem C) is dropped
    assert all(r.get("detections") for r in dets)
    # dets_only must be a strictly smaller payload than the full list
    assert len(json.dumps(dets)) < len(json.dumps(full))


def test_dets_only_rows_are_identical_to_filtering_the_full_list(app_ctx):
    """``dets_only`` is a server-side pushdown (empty-ground frames are never projected).

    It must stay byte-for-byte equal to filtering the full list — including ``frame_index``,
    which numbers every saved JPEG, not just the detection ones.
    """
    c = app_ctx.test_client()
    full = c.get("/missions/0001/frame_events?src=sim").get_json()
    dets = c.get("/missions/0001/frame_events?dets_only=1&src=sim").get_json()
    assert dets == [r for r in full if r.get("detections")]
    assert [r["frame_index"] for r in dets] == [0, 1]


def test_dets_only_frame_index_skips_empty_frames(app_ctx):
    """The empty-ground frame occupies index 2, so a later detection frame keeps its index."""
    c = app_ctx.test_client()
    full = c.get("/missions/0001/frame_events?src=sim").get_json()
    assert [r["frame_index"] for r in full] == [0, 1, 2]
    assert full[2]["detections"] == []


def test_frame_image_is_cacheable(app_ctx):
    """Frames are write-once; without an explicit Cache-Control the viewer re-validates
    every JPEG on every scrub."""
    c = app_ctx.test_client()
    r = c.get(f"/missions/0001/image?path=frames/{TS_A}.jpg&src=sim")
    assert r.status_code == 200
    cc = r.headers.get("Cache-Control", "")
    assert "public" in cc and "immutable" in cc
    assert "max-age=604800" in cc


def test_frame_image_thumbnail_is_cacheable(app_ctx):
    """The downscaled (max_side) branch must carry the same caching promise."""
    c = app_ctx.test_client()
    r = c.get(f"/missions/0001/image?path=frames/{TS_A}.jpg&max_side=64&src=sim")
    assert r.status_code == 200
    cc = r.headers.get("Cache-Control", "")
    assert "public" in cc and "max-age=604800" in cc


def test_frame_image_path_traversal_still_blocked(app_ctx):
    c = app_ctx.test_client()
    assert c.get("/missions/0001/image?path=../../etc/passwd&src=sim").status_code in (403, 404)


def test_detection_rows_have_ground_projections(app_ctx):
    """Map BBox layer needs lat/lon corners on each detection row."""
    c = app_ctx.test_client()
    dets = c.get("/missions/0001/frame_events?dets_only=1&src=sim").get_json()
    gps = [g for r in dets for g in (r.get("ground_projections") or [])]
    assert gps, "expected at least one ground projection"
    for g in gps:
        assert "center" in g and g["center"]["lat"] and g["center"]["lon"]


def test_dashboard_tab_endpoints_ok(app_ctx):
    """Each dashboard tab's primary endpoint responds 200 with a sane shape."""
    c = app_ctx.test_client()
    assert c.get("/missions/0001?src=sim").status_code == 200          # dashboard page
    assert c.get("/missions/0001/summary?src=sim").status_code == 200  # Report
    assert c.get("/missions/0001/timeline?src=sim").status_code == 200 # FSM Timeline
    assert c.get("/missions/0001/fsm?src=sim").status_code == 200
    assert c.get("/missions/0001/spray?src=sim").status_code == 200
    assert c.get("/missions/0001/path?src=sim").status_code == 200
    # Report's accuracy panel passes the truth file explicitly.
    assert c.get("/missions/0001/sim_compare?truth=cmac2.json&thresh_m=999999&src=sim").status_code == 200


# --- coverage across different mission data shapes -------------------------------------

def _build_app(root: Path, n_det: int, n_empty: int):
    """Mission 0001 with ``n_det`` detection frames + ``n_empty`` empty-ground frames."""
    mid = root / "0001"
    (mid / "frames").mkdir(parents=True)
    lines = [
        {"time_ns": 1704067201000000000, "ts": "2024-01-01T00:00:01.000Z", "level": "INFO",
         "logger": "main", "event": "mission_start", "schema_version": 2,
         "mission_id": "0001", "is_sim": True, "sim_truth_file": "cmac2.json"},
    ]
    ts = 1704067204000000000
    for _ in range(n_det):
        (mid / "frames" / f"{ts}.jpg").write_bytes(b"\xff\xd8\xff\xd9")
        lines.append(_fsm_tick(ts, "2024-01-01T00:00:04.000Z", ts, with_det=True))
        ts += 1_000_000
    for _ in range(n_empty):
        (mid / "frames" / f"{ts}.jpg").write_bytes(b"\xff\xd8\xff\xd9")
        lines.append(_fsm_tick(ts, "2024-01-01T00:00:04.000Z", ts, with_det=False))
        ts += 1_000_000
    (mid / "mission.jsonl").write_text(
        "\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    (root / "cmac2.json").write_text(json.dumps(
        {"weed_locations": [{"id": 0, "lat": -35.0002, "lon": 149.0002}]}), encoding="utf-8")
    app = create_app()
    app.config.update(MISSIONS_ROOT=root, RPI_MISSIONS_ROOT=root, SIM_DATA_ROOT=root, TESTING=True)
    return app


@pytest.mark.parametrize("n_det,n_empty", [
    (0, 5),    # no detections at all (pure ground)
    (1, 0),    # detections only
    (3, 10),   # mostly empty, a few detections (typical scan)
    (12, 4),   # detection-heavy
])
def test_invariants_hold_across_mission_shapes(n_det, n_empty):
    """The payload guarantees must hold for any mix of detection/empty frames."""
    with tempfile.TemporaryDirectory() as td:
        app = _build_app(Path(td), n_det, n_empty)
        c = app.test_client()
        full = c.get("/missions/0001/frame_events?src=sim").get_json()
        dets = c.get("/missions/0001/frame_events?dets_only=1&src=sim").get_json()

        assert len(full) == n_det + n_empty           # one row per saved JPEG
        assert len(dets) == n_det                     # dets_only drops empty-ground frames
        assert all(r.get("detections") for r in dets)
        # Never ship the history deques, on any row, for any shape.
        for r in full:
            ds = r.get("drone_state") or {}
            assert "rotation_history" not in ds and "gps_history" not in ds
        # Tabs still respond for this shape.
        assert c.get("/missions/0001/timeline?src=sim").status_code == 200
        assert c.get("/missions/0001?src=sim").status_code == 200
