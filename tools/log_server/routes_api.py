"""JSON API for mission logs."""

from __future__ import annotations

import json
from pathlib import Path

from flask import Blueprint, abort, jsonify, request, send_file, current_app

from services.analysis import (
    build_frame_events,
    build_summary_payload,
    build_timeline_payload,
    latest_sim_vision_event,
    sim_compare_payload,
    tail_json_events,
    camera_fov_polygons_from_fsm_ticks,
    telemetry_path_points,
    weed_prediction_points,
)
from services.mission_store import iter_events, resolve_mission_log

bp = Blueprint("log_api", __name__)


def _mission_log(mission_id: str) -> Path:
    p = resolve_mission_log(current_app.config["MISSIONS_ROOT"], mission_id)
    if p is None:
        abort(404)
    return p


@bp.get("/missions/<mission_id>/events")
def mission_events(mission_id: str):
    p = _mission_log(mission_id)
    limit = int(request.args.get("limit", "200"))
    events = []
    for ev in iter_events(p):
        events.append(ev)
        if len(events) >= limit:
            break
    return jsonify(events)


@bp.get("/missions/<mission_id>/fsm")
def mission_fsm(mission_id: str):
    p = _mission_log(mission_id)
    return jsonify([ev for ev in iter_events(p) if ev.get("event") == "fsm_transition"])


@bp.get("/missions/<mission_id>/weeds")
def mission_weeds(mission_id: str):
    p = _mission_log(mission_id)
    kinds = {"weed_detected", "weed_sprayed", "spray_attempt", "spray_miss", "spray_ready"}
    return jsonify([ev for ev in iter_events(p) if ev.get("event") in kinds])


@bp.get("/missions/<mission_id>/weeds/pred")
def mission_weeds_pred(mission_id: str):
    p = _mission_log(mission_id)
    do_dedup = request.args.get("dedup", "0") == "1"
    thresh_m = float(request.args.get("thresh_m", "0.5"))
    pts = weed_prediction_points(p, dedup=do_dedup, thresh_m=thresh_m)
    return jsonify(pts)


@bp.get("/missions/<mission_id>/path")
def mission_path(mission_id: str):
    """Drone path from telemetry_sample (GPS ~1 Hz). Use stride=1 for full resolution."""
    p = _mission_log(mission_id)
    stride = max(1, int(request.args.get("stride", "1")))
    return jsonify(telemetry_path_points(p, stride))


@bp.get("/missions/<mission_id>/camera_fov_footprints")
def mission_camera_fov_footprints(mission_id: str):
    """Camera FOV from each ``fsm_tick``. Query: ``stride`` (default 1), ``states`` (comma-separated, e.g. ``SCAN``) to restrict modes. Polygons include ``state`` for client coloring."""
    p = _mission_log(mission_id)
    stride = max(1, int(request.args.get("stride", "1")))
    raw_states = request.args.get("states", "").strip()
    if raw_states:
        states_filter = frozenset(
            p.strip().upper() for p in raw_states.split(",") if p.strip()
        )
    else:
        states_filter = None
    polys = camera_fov_polygons_from_fsm_ticks(p, stride, states_filter)
    return jsonify(
        {
            "stride": stride,
            "states_filter": sorted(states_filter) if states_filter else None,
            "polygons": polys,
        }
    )


@bp.get("/missions/<mission_id>/spray")
def mission_spray(mission_id: str):
    """All spray-related events."""
    p = _mission_log(mission_id)
    kinds = {"weed_sprayed", "spray_attempt", "spray_miss", "spray_ready", "spray_skipped"}
    return jsonify([ev for ev in iter_events(p) if ev.get("event") in kinds])


@bp.get("/missions/<mission_id>/timeline")
def mission_timeline(mission_id: str):
    """FSM state segments with wall-clock durations and visit counts."""
    p = _mission_log(mission_id)
    return jsonify(build_timeline_payload(p))


@bp.get("/missions/<mission_id>/summary")
def mission_summary(mission_id: str):
    """One-pass mission summary: header, duration, event counts, weed stats, insights."""
    p = _mission_log(mission_id)
    return jsonify(build_summary_payload(p))


@bp.get("/missions/<mission_id>/tail")
def mission_tail(mission_id: str):
    """Return new complete JSON lines since a byte offset — used by live mode."""
    p = _mission_log(mission_id)
    since_byte = int(request.args.get("since_byte", "0"))
    return jsonify(tail_json_events(p, since_byte))


@bp.get("/missions/<mission_id>/frame_events")
def mission_frame_events(mission_id: str):
    """Frame snapshots with detections; includes ``ground_projections`` and ``frame_footprint``.

    Inspect this JSON in the browser Network tab when debugging missing BBox ground
    overlays (vs path/prediction, which use other endpoints). Lines with ``frame`` but
    no ``detections`` are omitted.
    """
    p = _mission_log(mission_id)
    return jsonify(build_frame_events(p))


@bp.get("/missions/<mission_id>/sim_vision")
def mission_sim_vision(mission_id: str):
    """Latest sim vision parameters event (if any)."""
    p = _mission_log(mission_id)
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
    missions_root: Path = current_app.config["MISSIONS_ROOT"]
    mission_dir = (missions_root / mission_id).resolve()
    try:
        target = (mission_dir / rel).resolve()
        target.relative_to(mission_dir)
    except (ValueError, OSError):
        abort(403)
    if not target.is_file():
        abort(404)
    return send_file(target)


@bp.get("/missions/<mission_id>/sim_compare")
def mission_sim_compare(mission_id: str):
    truth_name = request.args.get("truth", "")
    thresh_m = float(request.args.get("thresh_m", "0.5"))
    if not truth_name or "/" in truth_name or "\\" in truth_name:
        abort(400)
    sim_root: Path = current_app.config["SIM_DATA_ROOT"]
    truth_path = sim_root / truth_name
    if not truth_path.exists():
        abort(404)

    p = _mission_log(mission_id)
    return jsonify(sim_compare_payload(p, sim_root, truth_name, thresh_m))
