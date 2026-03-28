"""HTML pages for the log server."""

from __future__ import annotations

import json
from pathlib import Path

from flask import Blueprint, Response, abort, current_app, redirect, render_template, url_for

from services.mission_store import mission_paths, resolve_mission_log, sim_files as list_sim_files
from services.mission_store import iter_events
from services.tile_cache import get_esri_jpg, get_osm_png

bp = Blueprint("log_web", __name__)


@bp.context_processor
def _tile_cache_urls():
    return {
        "tile_osm_url": url_for("log_web.tile_cache_osm", z=0, x=0, y=0).replace(
            "/0/0/0.png", "/{z}/{x}/{y}.png"
        ),
        "tile_esri_url": url_for("log_web.tile_cache_esri", z=0, y=0, x=0).replace(
            "/0/0/0.jpg", "/{z}/{y}/{x}.jpg"
        ),
    }


@bp.get("/tile_cache/osm/<int:z>/<int:x>/<int:y>.png")
def tile_cache_osm(z: int, x: int, y: int):
    root = current_app.config["TILE_CACHE_DIR"]
    try:
        data, mime = get_osm_png(root, z, x, y)
    except ValueError:
        abort(400)
    return Response(
        data,
        mimetype=mime,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@bp.get("/tile_cache/esri/<int:z>/<int:y>/<int:x>.jpg")
def tile_cache_esri(z: int, y: int, x: int):
    root = current_app.config["TILE_CACHE_DIR"]
    try:
        data, mime = get_esri_jpg(root, z, y, x)
    except ValueError:
        abort(400)
    return Response(
        data,
        mimetype=mime,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@bp.get("/")
def index():
    return redirect(url_for("log_web.compare_page"))


@bp.get("/missions")
def missions_list():
    missions_root: Path = current_app.config["MISSIONS_ROOT"]
    sim_root: Path = current_app.config["SIM_DATA_ROOT"]
    missions = [
        {"id": d.name, "path": str(d / "mission.jsonl"), "exists": (d / "mission.jsonl").exists()}
        for d in mission_paths(missions_root)
    ]
    return render_template(
        "index.html",
        missions=missions,
        sim_files=list_sim_files(sim_root),
        missions_path=str(missions_root),
        missions_root_exists=missions_root.exists(),
        sim_data_path=str(sim_root),
        sim_root_exists=sim_root.exists(),
    )


@bp.get("/missions/<mission_id>")
def mission_dashboard(mission_id: str):
    missions_root: Path = current_app.config["MISSIONS_ROOT"]
    sim_root: Path = current_app.config["SIM_DATA_ROOT"]
    p = resolve_mission_log(missions_root, mission_id)
    if p is None:
        abort(404)

    mission_ids = [
        d.name
        for d in mission_paths(missions_root)
        if (d / "mission.jsonl").exists()
    ]
    try:
        idx = mission_ids.index(mission_id)
    except ValueError:
        idx = -1
    prev_mission_id = mission_ids[idx - 1] if idx > 0 else None
    next_mission_id = mission_ids[idx + 1] if 0 <= idx < len(mission_ids) - 1 else None

    auto_truth = ""
    for ev in iter_events(p):
        if ev.get("event") == "mission_start":
            raw = ev.get("sim_truth_file", "") or ""
            auto_truth = Path(str(raw)).name if raw else ""
            break
    sf = list_sim_files(sim_root)
    return render_template(
        "mission_dashboard.html",
        mission_id=mission_id,
        log_path=str(p),
        sim_files=sf,
        mission_id_json=json.dumps(mission_id),
        sim_files_json=json.dumps(sf),
        auto_truth_json=json.dumps(auto_truth),
        auto_truth=auto_truth,
        prev_mission_id=prev_mission_id,
        next_mission_id=next_mission_id,
    )


@bp.get("/compare")
def compare_page():
    missions_root: Path = current_app.config["MISSIONS_ROOT"]
    sim_root: Path = current_app.config["SIM_DATA_ROOT"]
    missions = [
        {"id": d.name}
        for d in mission_paths(missions_root)
        if (d / "mission.jsonl").exists()
    ]
    from flask import request

    sel_a = request.args.get("a", "")
    sel_b = request.args.get("b", "")
    if not sel_a and not sel_b and len(missions) >= 2:
        sel_a = missions[-2]["id"]
        sel_b = missions[-1]["id"]
    return render_template(
        "compare.html",
        missions=missions,
        sim_files=list_sim_files(sim_root),
        sel_a=sel_a,
        sel_b=sel_b,
    )
