"""JSON API for mission logs."""

from __future__ import annotations

import json
import os
import shlex
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
    weed_prediction_points_from_detections,
    build_setup_scan_path,
)
from services.mission_store import (
    iter_events,
    resolve_mission_log,
    list_real_mission_setups,
    load_real_mission_setup,
    save_real_mission_setup,
    list_setups,
    load_setup,
    save_setup,
)
from services.geometry import grid_dedup

bp = Blueprint("log_api", __name__)

# Default mission ``params`` (same keys as ``main.py`` reads from setup JSON).
_SETUP_PARAM_DEFAULTS: dict[str, Any] = {
    "scan_height_m": 35,
    "scan_speed_ms": 1.0,
    "min_dist_from_waypoint_m": 1,
    "min_weed_spacing_m": 2,
    "min_num_det": 3,
    "goto_alt_m": 10,
    "max_homing_dist_m": 10,
    "min_alt_m": 5,
    "max_homing_alt_m": 15,
    "min_spray_error_m": 2,
    "sim_ai_enable_imperfections": False,
}

# In-memory cache for expensive FOV scans (invalidated when mission.jsonl mtime/size changes).
_FOV_CACHE: OrderedDict[tuple[Any, ...], dict[str, Any]] = OrderedDict()
_FOV_CACHE_MAX = 16


def _coerce_setup_params(obj: Any) -> dict[str, Any]:
    if not isinstance(obj, dict):
        raise ValueError("params must be a JSON object")
    out = dict(_SETUP_PARAM_DEFAULTS)
    int_keys = (
        "scan_height_m",
        "min_dist_from_waypoint_m",
        "min_weed_spacing_m",
        "min_num_det",
        "goto_alt_m",
        "max_homing_dist_m",
        "min_alt_m",
        "max_homing_alt_m",
        "min_spray_error_m",
    )
    for k, v in obj.items():
        if k not in _SETUP_PARAM_DEFAULTS:
            raise ValueError(f"unknown params key: {k}")
        if k == "scan_speed_ms":
            out[k] = float(v)
        elif k == "sim_ai_enable_imperfections":
            out[k] = bool(v)
        elif k in int_keys:
            out[k] = int(v)
        else:
            out[k] = v
    return out


def _setup_payload_from_json(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("Payload must be a JSON object")
    fc = data.get("field_center")
    weeds = data.get("weed_locations")
    scan = data.get("scan_path")
    if not isinstance(fc, list) or len(fc) != 2:
        raise ValueError("field_center must be [lat, lon]")
    if not isinstance(weeds, list):
        raise ValueError("weed_locations must be a list")
    if not isinstance(scan, list):
        raise ValueError("scan_path must be a list")
    field_center = [float(fc[0]), float(fc[1])]
    weed_locations: list[dict[str, Any]] = []
    for i, w in enumerate(weeds):
        if not isinstance(w, dict):
            raise ValueError("Each weed location must be an object")
        lat = float(w["lat"])
        lon = float(w["lon"])
        wid = int(w.get("id", i))
        weed_locations.append({"id": wid, "lat": lat, "lon": lon})
    scan_path: list[list[float]] = []
    for p in scan:
        if not isinstance(p, list) or len(p) != 2:
            raise ValueError("Each scan_path point must be [lat, lon]")
        scan_path.append([float(p[0]), float(p[1])])
    params_raw = data.get("params")
    if params_raw is None:
        params = dict(_SETUP_PARAM_DEFAULTS)
    else:
        params = _coerce_setup_params(params_raw)
    return {
        "field_center": field_center,
        "weed_locations": weed_locations,
        "scan_path": scan_path,
        "params": params,
    }


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

    spacing_raw = request.args.get("spacing_m")
    min_num_det_raw = request.args.get("min_num_det")
    if spacing_raw is not None and min_num_det_raw is not None:
        spacing_m = float(spacing_raw)
        min_num_det = int(min_num_det_raw)
        pts = weed_prediction_points_from_detections(
            p, spacing_m=spacing_m, min_num_det=min_num_det
        )
        if do_dedup:
            pts = grid_dedup(pts, thresh_m)
    else:
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
    spacing_m_raw = request.args.get("spacing_m")
    min_num_det_raw = request.args.get("min_num_det")
    spacing_m = float(spacing_m_raw) if spacing_m_raw is not None else None
    min_num_det = int(min_num_det_raw) if min_num_det_raw is not None else None

    return jsonify(
        sim_compare_payload(
            p,
            truth_path,
            thresh_m,
            spacing_m=spacing_m,
            min_num_det=min_num_det,
        )
    )


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


@bp.get("/missions/<mission_id>/setup_files")
def mission_setup_files(mission_id: str):
    if not mission_id.isdigit():
        abort(400)
    return jsonify({"files": list_real_mission_setups()})


@bp.get("/setup_files")
def setup_files():
    target = request.args.get("target", "real")
    sim_root: Path = current_app.config["SIM_DATA_ROOT"]
    return jsonify({"files": list_setups(target, sim_root), "target": target})


@bp.get("/missions/<mission_id>/setup_file")
def mission_setup_file_get(mission_id: str):
    if not mission_id.isdigit():
        abort(400)
    name = request.args.get("name", "")
    try:
        payload = load_real_mission_setup(name)
    except FileNotFoundError:
        abort(404)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"name": name, "payload": payload})


@bp.get("/setup_file")
def setup_file_get():
    name = request.args.get("name", "")
    target = request.args.get("target", "real")
    sim_root: Path = current_app.config["SIM_DATA_ROOT"]
    try:
        payload = load_setup(name, target, sim_root)
    except FileNotFoundError:
        abort(404)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"name": name, "payload": payload, "target": target})


@bp.post("/missions/<mission_id>/setup_file")
def mission_setup_file_save(mission_id: str):
    if not mission_id.isdigit():
        abort(400)
    body = request.get_json(silent=True) or {}
    name = str(body.get("name", "")).strip()
    payload_raw = body.get("payload")
    try:
        payload = _setup_payload_from_json(payload_raw)
        p = save_real_mission_setup(name, payload)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "name": p.name, "path": str(p)})


@bp.post("/setup_file")
def setup_file_save():
    body = request.get_json(silent=True) or {}
    name = str(body.get("name", "")).strip()
    target = str(body.get("target", "real")).strip().lower()
    payload_raw = body.get("payload")
    sim_root: Path = current_app.config["SIM_DATA_ROOT"]
    try:
        payload = _setup_payload_from_json(payload_raw)
        p = save_setup(name, payload, target, sim_root)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "name": p.name, "path": str(p), "target": target})


@bp.post("/missions/<mission_id>/setup_scan_path")
def mission_setup_scan_path(mission_id: str):
    if not mission_id.isdigit():
        abort(400)
    body = request.get_json(silent=True) or {}
    weeds = body.get("weed_locations") or []
    lane_step_m = float(body.get("lane_step_m", 8.0))
    pad_m = float(body.get("pad_m", 3.0))
    scan_path = build_setup_scan_path(weeds, lane_step_m=lane_step_m, pad_m=pad_m)
    return jsonify({"scan_path": scan_path, "count": len(scan_path)})


@bp.post("/setup_scan_path")
def setup_scan_path():
    body = request.get_json(silent=True) or {}
    weeds = body.get("weed_locations") or []
    lane_step_m = float(body.get("lane_step_m", 8.0))
    pad_m = float(body.get("pad_m", 3.0))
    scan_path = build_setup_scan_path(weeds, lane_step_m=lane_step_m, pad_m=pad_m)
    return jsonify({"scan_path": scan_path, "count": len(scan_path)})


def _rpi_ssh_user_at_host() -> str:
    """e.g. ``fred@rpi.local`` — override with ``SKYDOCK_RPI_SSH``."""
    return os.environ.get("SKYDOCK_RPI_SSH", "fred@rpi.local").strip() or "fred@rpi.local"


def _rpi_remote_skydock_path() -> str:
    """Directory on the Pi that contains ``missions/`` and ``real_missions/`` (``~`` expanded on the Pi)."""
    return os.environ.get("SKYDOCK_RPI_REMOTE_DIR", "~/skydock2").rstrip("/")


def _rpi_ssh_base_args() -> list[str]:
    return [
        "ssh",
        "-o",
        "ConnectTimeout=8",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=no",
    ]


def _rpi_remote_cd_expr(remote_chdir: str) -> str:
    """Shell fragment for ``cd`` on the Pi: ``~/foo`` → ``$HOME/foo`` so tilde expands."""
    s = remote_chdir.strip()
    if s.startswith("~/"):
        return f'"$HOME/{s[2:]}"'
    return shlex.quote(s)


def _rpi_tar_ssh_pull(
    user_host: str,
    remote_chdir: str,
    remote_topdir: str,
    local_dest: Path,
    *,
    timeout_s: int = 300,
) -> tuple[int, str]:
    """Stream ``tar czf -`` from ``remote_chdir/remote_topdir`` over SSH and unpack into ``local_dest``.

    Uses ``--strip-components=1`` so ``missions/0001/...`` → ``local_dest/0001/...`` (same for ``real_missions``).
    """
    local_dest.mkdir(parents=True, exist_ok=True)
    rcmd = f"cd {_rpi_remote_cd_expr(remote_chdir)} && tar czf - {shlex.quote(remote_topdir)}"
    ssh_cmd = _rpi_ssh_base_args() + [user_host, rcmd]
    out_parts: list[str] = []
    with subprocess.Popen(
        ssh_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as p_ssh:
        assert p_ssh.stdout is not None
        try:
            tar = subprocess.run(
                [
                    "tar",
                    "-xzf",
                    "-",
                    "-C",
                    str(local_dest),
                    "--strip-components=1",
                ],
                stdin=p_ssh.stdout,
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
        finally:
            p_ssh.stdout.close()
        _out_ssh, err_ssh = p_ssh.communicate(timeout=timeout_s)
        rc_ssh = p_ssh.returncode
        if err_ssh:
            out_parts.append(err_ssh)
        if tar.stderr:
            out_parts.append(tar.stderr)
        if tar.stdout:
            out_parts.append(tar.stdout)
        rc = rc_ssh if rc_ssh != 0 else tar.returncode
        return rc, "\n".join(s for s in out_parts if s).strip()


def _rpi_resolve_host() -> str | None:
    """Return a host name that answers SSH, or None. Honors ``SKYDOCK_RPI_SSH`` (e.g. ``fred@rpi.local``) first."""
    ssh_opts = ["-o", "ConnectTimeout=8", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no"]
    spec = os.environ.get("SKYDOCK_RPI_SSH", "").strip()
    if spec and "@" in spec:
        try:
            r = subprocess.run(["ssh"] + ssh_opts + [spec, "exit"], timeout=10)
            if r.returncode == 0:
                return spec.split("@", 1)[1].strip()
        except Exception:
            pass
    for host in ["rpi.local", "10.0.0.1"]:
        try:
            r = subprocess.run(["ssh"] + ssh_opts + [f"fred@{host}", "exit"], timeout=10)
            if r.returncode == 0:
                return host
        except Exception:
            pass
    return None


@bp.post("/api/sync/rpi")
def sync_rpi():
    """Pull ``real_missions/`` and ``missions/`` from the RPi: remote ``tar czf -`` over SSH, unpack locally.

    Uses ``SKYDOCK_RPI_SSH`` (default ``fred@rpi.local``) and ``SKYDOCK_RPI_REMOTE_DIR`` (default ``~/skydock2``).
    Mission logs land in ``RPI_MISSIONS_ROOT`` (see ``SKYDOCK_RPI_MISSIONS_DIR``).
    """
    if _rpi_resolve_host() is None:
        return jsonify(
            {
                "ok": False,
                "error": "Cannot reach RPi over SSH (try SKYDOCK_RPI_SSH=fred@rpi.local or check the Pi is on the network).",
            }
        ), 502

    repo_root = Path(__file__).resolve().parent.parent.parent
    user_host = _rpi_ssh_user_at_host()
    remote = _rpi_remote_skydock_path()

    rpi_missions: Path = current_app.config["RPI_MISSIONS_ROOT"]
    real_missions = repo_root / "real_missions"

    pulls: list[tuple[str, str, Path]] = [
        ("real_missions (tar → unpack)", "real_missions", real_missions),
        ("missions → rpi_missions (tar → unpack)", "missions", rpi_missions),
    ]
    chunks: list[str] = []
    rc = 0
    for label, topdir, dest in pulls:
        code, out = _rpi_tar_ssh_pull(user_host, remote, topdir, dest)
        chunks.append(f"=== {label} ===\n{out or '(no output)'}")
        if code != 0:
            rc = code
            break

    output = "\n\n".join(chunks)
    if rc == 0:
        return jsonify({"ok": True, "output": output})
    return jsonify({"ok": False, "error": output})


@bp.post("/api/rpi/pull_missions")
def rpi_pull_missions():
    """Pull only remote ``missions/`` into local ``rpi_missions/`` (tar stream + unpack; same as sync step 2)."""
    if _rpi_resolve_host() is None:
        return jsonify(
            {
                "ok": False,
                "error": "Cannot reach RPi over SSH (try SKYDOCK_RPI_SSH=fred@rpi.local).",
            }
        ), 502
    user_host = _rpi_ssh_user_at_host()
    remote = _rpi_remote_skydock_path()
    rpi_missions: Path = current_app.config["RPI_MISSIONS_ROOT"]
    code, out = _rpi_tar_ssh_pull(user_host, remote, "missions", rpi_missions)
    if code == 0:
        return jsonify({"ok": True, "output": out or "(no output)"})
    return jsonify({"ok": False, "error": out}), 500


@bp.post("/api/rpi/push_real_missions")
def rpi_push_real_missions():
    """rsync local real_missions/ → RPi."""
    if _rpi_resolve_host() is None:
        return jsonify({"status": "error", "output": "Cannot reach RPi (set SKYDOCK_RPI_SSH=fred@rpi.local)"}), 502
    repo_root = Path(__file__).resolve().parent.parent.parent
    src = str(repo_root / "real_missions") + "/"
    user_host = _rpi_ssh_user_at_host()
    remote = _rpi_remote_skydock_path()
    ssh_cmd = "ssh -o ConnectTimeout=8 -o BatchMode=yes -o StrictHostKeyChecking=no"
    try:
        result = subprocess.run(
            ["rsync", "-avz", "-e", ssh_cmd, src, f"{user_host}:{remote}/real_missions/"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        out = (result.stdout + result.stderr).strip()
        if result.returncode != 0:
            return jsonify({"status": "error", "output": out}), 500
        return jsonify({"status": "ok", "output": out})
    except subprocess.TimeoutExpired:
        return jsonify({"status": "error", "output": "Timed out"}), 504
    except Exception as exc:
        return jsonify({"status": "error", "output": str(exc)}), 500


@bp.post("/api/rpi/pull_real_missions")
def rpi_pull_real_missions():
    """RPi ``real_missions/`` → local via tar stream + unpack."""
    if _rpi_resolve_host() is None:
        return jsonify({"status": "error", "output": "Cannot reach RPi (set SKYDOCK_RPI_SSH=fred@rpi.local)"}), 502
    repo_root = Path(__file__).resolve().parent.parent.parent
    dest = repo_root / "real_missions"
    user_host = _rpi_ssh_user_at_host()
    remote = _rpi_remote_skydock_path()
    code, out = _rpi_tar_ssh_pull(user_host, remote, "real_missions", dest, timeout_s=120)
    if code == 0:
        return jsonify({"status": "ok", "output": out or "(no output)"})
    return jsonify({"status": "error", "output": out}), 500
