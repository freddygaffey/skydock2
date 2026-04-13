"""HTML pages for the log server."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from flask import Blueprint, abort, current_app, redirect, render_template, request, url_for

from services.mission_store import mission_paths, resolve_mission_log, sim_files as list_sim_files
from services.mission_store import truth_files_for_ui
from services.mission_store import list_real_mission_setups
from services.mission_store import iter_events
from services.mission_index import default_index_path, index_matches_log
from services.training_data import (
    default_model_path,
    default_stream_batch_size,
    training_yolo_models_for_ui,
)
from services.tile_cache import ESRI_URL, OSM_URL

bp = Blueprint("log_web", __name__)

# Logs larger than this without an index get a stronger “build index” hint (bytes).
_LARGE_LOG_BYTES = 5 * 1024 * 1024


def _nav_urls_for_mission(mission_id: str, src: str) -> dict[str, str]:
    """Log / weed / GC links scoped to one mission (avoids jumping to “latest”)."""
    return {
        "log_url": url_for("log_web.mission_dashboard", mission_id=mission_id, src=src),
        "weed_url": url_for("log_web.mission_weed_marking_page", mission_id=mission_id, src=src),
        "gc_url": url_for("log_web.mission_gc_page", mission_id=mission_id, src=src),
        "training_url": url_for("log_web.mission_training_page", mission_id=mission_id, src=src),
    }


def _mission_page_common(mission_id: str) -> dict[str, Any]:
    """Shared template vars for mission_id pages (log / weed marking / GC)."""
    src = request.args.get("src", "sim")
    missions_root = _missions_root(src)
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
    sf = truth_files_for_ui(sim_root, src)
    return {
        "mission_id": mission_id,
        "mission_ids": mission_ids,
        "log_path": str(p),
        "sim_files": sf,
        "mission_id_json": json.dumps(mission_id),
        "mission_ids_json": json.dumps(mission_ids),
        "sim_files_json": json.dumps(sf),
        "auto_truth_json": json.dumps(auto_truth),
        "auto_truth": auto_truth,
        "prev_mission_id": prev_mission_id,
        "next_mission_id": next_mission_id,
        "src": src,
        "src_json": json.dumps(src),
    }


def _missions_root(src: str | None = None) -> Path:
    if src == "rpi":
        return current_app.config["RPI_MISSIONS_ROOT"]
    return current_app.config["MISSIONS_ROOT"]


def _latest_mission_id(src: str) -> str | None:
    mids = [
        d.name
        for d in mission_paths(_missions_root(src))
        if (d / "mission.jsonl").exists()
    ]
    return mids[-1] if mids else None


@bp.context_processor
def _leaflet_tile_urls():
    """Direct tile streaming (browser → OSM / Esri); no local disk cache on the log server."""
    return {"tile_osm_url": OSM_URL, "tile_esri_url": ESRI_URL}


@bp.get("/")
def index():
    return redirect(url_for("log_web.missions_list"))


@bp.get("/missions")
def missions_list():
    src = request.args.get("src", "sim")
    missions_root = _missions_root(src)
    sim_root: Path = current_app.config["SIM_DATA_ROOT"]
    missions = [
        {"id": d.name, "path": str(d / "mission.jsonl"), "exists": (d / "mission.jsonl").exists()}
        for d in mission_paths(missions_root)
    ]
    return render_template(
        "index.html",
        missions=missions,
        sim_files=truth_files_for_ui(sim_root, src),
        missions_path=str(missions_root),
        missions_root_exists=missions_root.exists(),
        sim_data_path=str(sim_root),
        sim_root_exists=sim_root.exists(),
        src=src,
    )


@bp.get("/missions/<mission_id>")
def mission_dashboard(mission_id: str):
    ctx = _mission_page_common(mission_id)
    nav = _nav_urls_for_mission(mission_id, ctx["src"])
    log_p = Path(ctx["log_path"])
    ip = default_index_path(log_p)
    index_ready = index_matches_log(log_p, ip)
    try:
        log_size_bytes = log_p.stat().st_size
    except OSError:
        log_size_bytes = 0
    large_log_hint = (log_size_bytes >= _LARGE_LOG_BYTES) and (not index_ready)
    return render_template(
        "mission_dashboard.html",
        nav_active="log",
        index_ready=index_ready,
        index_path=str(ip),
        log_size_bytes=log_size_bytes,
        large_log_hint=large_log_hint,
        **nav,
        **ctx,
    )


@bp.get("/missions/<mission_id>/weed-marking")
def mission_weed_marking_page(mission_id: str):
    ctx = _mission_page_common(mission_id)
    nav = _nav_urls_for_mission(mission_id, ctx["src"])
    return render_template(
        "mission_weed_marking.html",
        nav_active="weed",
        **nav,
        **ctx,
    )


@bp.get("/missions/<mission_id>/training")
def mission_training_page(mission_id: str):
    ctx = _mission_page_common(mission_id)
    nav = _nav_urls_for_mission(mission_id, ctx["src"])
    return render_template(
        "mission_training.html",
        nav_active="training",
        real_mission_files=list_real_mission_setups(),
        default_yolo_model=default_model_path(),
        default_yolo_batch=default_stream_batch_size(),
        **training_yolo_models_for_ui(),
        **nav,
        **ctx,
    )


@bp.get("/missions/<mission_id>/gc")
def mission_gc_page(mission_id: str):
    ctx = _mission_page_common(mission_id)
    nav = _nav_urls_for_mission(mission_id, ctx["src"])
    return render_template(
        "mission_gc.html",
        nav_active="gc",
        **nav,
        **ctx,
    )


@bp.get("/weed-marking")
def weed_marking():
    """Short URL: weed marking for the latest mission (same data as /missions/<id>/weed-marking)."""
    src = request.args.get("src", "sim")
    latest = _latest_mission_id(src)
    if latest is None:
        return redirect(url_for("log_web.missions_list", src=src))
    ctx = _mission_page_common(latest)
    nav = _nav_urls_for_mission(latest, src)
    return render_template(
        "mission_weed_marking.html",
        nav_active="weed",
        latest_shortcut=True,
        **nav,
        **ctx,
    )


@bp.get("/gc")
def gc_page():
    """Short URL: GC for the latest mission."""
    src = request.args.get("src", "sim")
    latest = _latest_mission_id(src)
    if latest is None:
        return redirect(url_for("log_web.missions_list", src=src))
    ctx = _mission_page_common(latest)
    nav = _nav_urls_for_mission(latest, src)
    return render_template(
        "mission_gc.html",
        nav_active="gc",
        latest_shortcut=True,
        **nav,
        **ctx,
    )


@bp.get("/compare")
def compare_page():
    src = request.args.get("src", "sim")
    missions_root = _missions_root(src)
    sim_root: Path = current_app.config["SIM_DATA_ROOT"]
    missions = [
        {"id": d.name}
        for d in mission_paths(missions_root)
        if (d / "mission.jsonl").exists()
    ]
    sel_a = request.args.get("a", "")
    sel_b = request.args.get("b", "")
    if not sel_a and not sel_b and len(missions) >= 2:
        sel_a = missions[-2]["id"]
        sel_b = missions[-1]["id"]
    latest = _latest_mission_id(src)
    if latest:
        nav = _nav_urls_for_mission(latest, src)
    else:
        nav = {
            "log_url": url_for("log_web.missions_list", src=src),
            "weed_url": url_for("log_web.weed_marking", src=src),
            "gc_url": url_for("log_web.gc_page", src=src),
            "training_url": url_for("log_web.missions_list", src=src),
        }
    return render_template(
        "compare.html",
        nav_active="log",
        **nav,
        missions=missions,
        sim_files=truth_files_for_ui(sim_root, src),
        sel_a=sel_a,
        sel_b=sel_b,
        src=src,
        src_json=json.dumps(src),
    )
