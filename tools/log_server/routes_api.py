"""JSON API for mission logs."""

from __future__ import annotations

import json
import subprocess
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any

from flask import Blueprint, abort, jsonify, request, send_file, current_app

from services.analysis import (
    build_frame_events,
    build_summary_payload,
    build_timeline_payload,
    latest_sim_vision_event,
    resolve_truth_json_path,
    sim_compare_payload,
    tail_json_events,
    camera_fov_polygons_from_fsm_ticks,
    fsm_tick_path_points,
    telemetry_path_points,
    weed_prediction_points,
)
from services.mission_store import iter_events, resolve_mission_log

bp = Blueprint("log_api", __name__)

# In-memory cache for expensive FOV scans (invalidated when mission.jsonl mtime/size changes).
_FOV_CACHE: OrderedDict[tuple[Any, ...], dict[str, Any]] = OrderedDict()
_FOV_CACHE_MAX = 16


def _fov_cache_key(path: Path, stride: int, states_filter: frozenset[str] | None, max_polygons: int) -> tuple[Any, ...]:
    st = path.stat()
    sf = tuple(sorted(states_filter)) if states_filter is not None else None
    return (str(path.resolve()), st.st_mtime_ns, st.st_size, stride, sf, max_polygons)


def _fov_cache_get(key: tuple[Any, ...]) -> dict[str, Any] | None:
    if key not in _FOV_CACHE:
        return None
    _FOV_CACHE.move_to_end(key)
    return _FOV_CACHE[key]


def _fov_cache_set(key: tuple[Any, ...], payload: dict[str, Any]) -> None:
    _FOV_CACHE[key] = payload
    _FOV_CACHE.move_to_end(key)
    while len(_FOV_CACHE) > _FOV_CACHE_MAX:
        _FOV_CACHE.popitem(last=False)


def _missions_root(src: str | None = None) -> Path:
    if src == "rpi":
        return current_app.config["RPI_MISSIONS_ROOT"]
    return current_app.config["MISSIONS_ROOT"]


def _mission_log(mission_id: str, src: str | None = None) -> Path:
    p = resolve_mission_log(_missions_root(src), mission_id)
    if p is None:
        abort(404)
    return p


@bp.get("/missions/<mission_id>/events")
def mission_events(mission_id: str):
    src = request.args.get("src", "sim")
    p = _mission_log(mission_id, src)
    limit = int(request.args.get("limit", "200"))
    events = []
    for ev in iter_events(p):
        events.append(ev)
        if len(events) >= limit:
            break
    return jsonify(events)


@bp.get("/missions/<mission_id>/fsm")
def mission_fsm(mission_id: str):
    src = request.args.get("src", "sim")
    p = _mission_log(mission_id, src)
    return jsonify([ev for ev in iter_events(p) if ev.get("event") == "fsm_transition"])


@bp.get("/missions/<mission_id>/weeds")
def mission_weeds(mission_id: str):
    src = request.args.get("src", "sim")
    p = _mission_log(mission_id, src)
    kinds = {"weed_detected", "weed_sprayed", "spray_attempt", "spray_miss", "spray_ready"}
    return jsonify([ev for ev in iter_events(p) if ev.get("event") in kinds])


@bp.get("/missions/<mission_id>/weeds/pred")
def mission_weeds_pred(mission_id: str):
    src = request.args.get("src", "sim")
    p = _mission_log(mission_id, src)
    do_dedup = request.args.get("dedup", "0") == "1"
    thresh_m = float(request.args.get("thresh_m", "0.5"))
    pts = weed_prediction_points(p, dedup=do_dedup, thresh_m=thresh_m)
    return jsonify(pts)


@bp.get("/missions/<mission_id>/path")
def mission_path(mission_id: str):
    """Drone path GPS: ``source=telemetry`` (``telemetry_sample`` ~1 Hz) or ``source=fsm`` (``fsm_tick``, aligns with camera / bbox projection)."""
    src = request.args.get("src", "sim")
    p = _mission_log(mission_id, src)
    stride = max(1, int(request.args.get("stride", "1")))
    source = (request.args.get("source") or "telemetry").strip().lower()
    if source in ("fsm", "fsm_tick", "tick"):
        return jsonify(fsm_tick_path_points(p, stride))
    return jsonify(telemetry_path_points(p, stride))


@bp.get("/missions/<mission_id>/camera_fov_footprints")
def mission_camera_fov_footprints(mission_id: str):
    """Camera FOV from each ``fsm_tick``. Query: ``stride`` (default 8), ``max_polygons`` (omit or 0 = no cap; positive = limit rows after stride), ``states`` (comma-separated FSM names). Cached per log file revision."""
    src = request.args.get("src", "sim")
    p = _mission_log(mission_id, src)
    stride = max(1, int(request.args.get("stride", "8")))
    raw_mp = request.args.get("max_polygons", "").strip()
    if raw_mp == "":
        max_polygons: int | None = None
    else:
        try:
            v = int(raw_mp)
            max_polygons = None if v <= 0 else v
        except ValueError:
            max_polygons = None
    raw_states = request.args.get("states", "").strip()
    if raw_states.upper() == "__NONE__":
        states_filter: frozenset[str] | None = frozenset()
    elif raw_states:
        states_filter = frozenset(
            p.strip().upper() for p in raw_states.split(",") if p.strip()
        )
    else:
        states_filter = None

    cache_key = _fov_cache_key(p, stride, states_filter, 0 if max_polygons is None else max_polygons)
    cached = _fov_cache_get(cache_key)
    if cached is not None:
        return jsonify(cached)

    polys, capped, raw_n = camera_fov_polygons_from_fsm_ticks(
        p, stride, states_filter, max_polygons
    )
    st = p.stat()
    payload = {
        "stride": stride,
        "states_filter": sorted(states_filter) if states_filter is not None else None,
        "polygons": polys,
        "polygons_capped": capped,
        "polygons_total_before_cap": raw_n if capped else None,
        "polygon_cap": max_polygons,
        "source_log_rev": f"{st.st_mtime_ns}-{st.st_size}",
    }
    _fov_cache_set(cache_key, payload)
    return jsonify(payload)


@bp.get("/missions/<mission_id>/spray")
def mission_spray(mission_id: str):
    """All spray-related events."""
    src = request.args.get("src", "sim")
    p = _mission_log(mission_id, src)
    kinds = {"weed_sprayed", "spray_attempt", "spray_miss", "spray_ready", "spray_skipped"}
    return jsonify([ev for ev in iter_events(p) if ev.get("event") in kinds])


@bp.get("/missions/<mission_id>/timeline")
def mission_timeline(mission_id: str):
    """FSM state segments with wall-clock durations and visit counts."""
    src = request.args.get("src", "sim")
    p = _mission_log(mission_id, src)
    return jsonify(build_timeline_payload(p))


@bp.get("/missions/<mission_id>/summary")
def mission_summary(mission_id: str):
    """One-pass mission summary: header, duration, event counts, weed stats, insights."""
    src = request.args.get("src", "sim")
    p = _mission_log(mission_id, src)
    return jsonify(build_summary_payload(p))


@bp.get("/missions/<mission_id>/tail")
def mission_tail(mission_id: str):
    """Return new complete JSON lines since a byte offset — used by live mode."""
    src = request.args.get("src", "sim")
    p = _mission_log(mission_id, src)
    since_byte = int(request.args.get("since_byte", "0"))
    return jsonify(tail_json_events(p, since_byte))


@bp.get("/missions/<mission_id>/frame_events")
def mission_frame_events(mission_id: str):
    """Frame snapshots with detections; includes ``ground_projections`` and ``frame_footprint``.

    Inspect this JSON in the browser Network tab when debugging missing BBox ground
    overlays (vs path/prediction, which use other endpoints). Lines with ``frame`` but
    no ``detections`` are omitted — except for real missions where frames/ directory
    is scanned and matched by timestamp.
    """
    src = request.args.get("src", "sim")
    p = _mission_log(mission_id, src)
    mission_dir = _missions_root(src) / mission_id
    return jsonify(build_frame_events(p, mission_dir))


@bp.get("/missions/<mission_id>/sim_vision")
def mission_sim_vision(mission_id: str):
    """Latest sim vision parameters event (if any)."""
    src = request.args.get("src", "sim")
    p = _mission_log(mission_id, src)
    latest = latest_sim_vision_event(p)
    if latest is None:
        return jsonify(None)
    return jsonify(latest)


@bp.get("/missions/<mission_id>/image")
def mission_image(mission_id: str):
    """Serve a real image file from within the mission directory."""
    if not mission_id.isdigit():
        abort(400)
    rel = request.args.get("path", "")
    if not rel:
        abort(400)
    src = request.args.get("src", "sim")
    missions_root = _missions_root(src)
    mission_dir = (missions_root / mission_id).resolve()
    try:
        target = (mission_dir / rel).resolve()
        target.relative_to(mission_dir)
    except (ValueError, OSError):
        abort(403)
    if not target.is_file():
        abort(404)
    return send_file(target)


@bp.get("/missions/<mission_id>/video")
def mission_video(mission_id: str):
    """Serve the mission video file (mission_video.mp4) if it exists."""
    if not mission_id.isdigit():
        abort(400)
    src = request.args.get("src", "sim")
    missions_root = _missions_root(src)
    video_path = (missions_root / mission_id / "mission_video.mp4").resolve()
    try:
        video_path.relative_to(missions_root.resolve())
    except ValueError:
        abort(403)
    if not video_path.is_file():
        abort(404)
    # conditional=True enables Range requests (seeking / streaming in <video>)
    return send_file(video_path, mimetype="video/mp4", conditional=True)


@bp.get("/missions/<mission_id>/sim_compare")
def mission_sim_compare(mission_id: str):
    truth_name = request.args.get("truth", "")
    thresh_m = float(request.args.get("thresh_m", "0.5"))
    if not truth_name or "/" in truth_name or "\\" in truth_name:
        abort(400)
    sim_root: Path = current_app.config["SIM_DATA_ROOT"]
    truth_path = resolve_truth_json_path(sim_root, truth_name)
    if truth_path is None:
        abort(404)

    src = request.args.get("src", "sim")
    p = _mission_log(mission_id, src)
    return jsonify(sim_compare_payload(p, truth_path, thresh_m))


@bp.post("/missions/<mission_id>/generate_video")
def mission_generate_video(mission_id: str):
    """Start make_video.py for a mission in the background. Returns immediately."""
    if not mission_id.isdigit():
        abort(400)
    src = request.args.get("src", "sim")
    missions_root = _missions_root(src)
    mission_dir = (missions_root / mission_id).resolve()
    if not mission_dir.is_dir():
        abort(404)
    log_path = mission_dir / "mission.jsonl"
    if not log_path.exists():
        abort(404)
    repo_root = Path(__file__).resolve().parent.parent.parent
    script = repo_root / "tools" / "make_video.py"
    if not script.exists():
        return jsonify({"ok": False, "error": f"make_video.py not found at {script}"}), 404
    try:
        subprocess.Popen(
            [sys.executable, str(script), str(mission_dir)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return jsonify({"ok": True, "mission_dir": str(mission_dir)})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)})


@bp.post("/api/sync/rpi")
def sync_rpi():
    """Run pull_logs_rpi.sh to sync missions from the RPi."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    script = (repo_root / "pull_logs_rpi.sh").resolve()
    if not script.is_file():
        return jsonify({"ok": False, "error": f"Script not found: {script}"}), 404
    try:
        result = subprocess.run(
            ["bash", str(script)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = (result.stdout + result.stderr).strip()
        if result.returncode == 0:
            return jsonify({"ok": True, "output": output})
        else:
            return jsonify({"ok": False, "error": output})
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "Sync timed out after 60s"})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)})
