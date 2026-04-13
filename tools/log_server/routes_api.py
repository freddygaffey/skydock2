"""JSON API for mission logs."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from flask import Blueprint, abort, jsonify, request, send_file, current_app, Response, stream_with_context

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
from services.mission_cache import MISSION_READ_CACHE

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
    return ("fov", str(path.resolve()), st.st_mtime_ns, st.st_size, stride, sf, max_polygons)


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
    cached = MISSION_READ_CACHE.get(cache_key)
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
    MISSION_READ_CACHE.set(cache_key, payload)
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


@bp.post("/missions/<mission_id>/index")
def mission_index_build(mission_id: str):
    """Build or refresh ``mission_index.sqlite`` next to this mission's ``mission.jsonl``."""
    src = request.args.get("src", "sim")
    p = _mission_log(mission_id, src)
    from services.mission_index import build_mission_index

    try:
        out = build_mission_index(p, force=True)
    except OSError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "index_path": str(out)})


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
    """Serve a real image file from within the mission directory.

    Optional ``max_side`` (32–640): downscale JPEG/PNG in-process for thumbnails
    and training main view (640). Falls back to the original file if OpenCV is unavailable.
    """
    if not mission_id.isdigit():
        abort(400)
    rel = request.args.get("path", "")
    if not rel:
        abort(400)
    src = request.args.get("src", "sim")
    max_side = request.args.get("max_side", type=int)
    missions_root = _missions_root(src)
    mission_dir = (missions_root / mission_id).resolve()
    try:
        target = (mission_dir / rel).resolve()
        target.relative_to(mission_dir)
    except (ValueError, OSError):
        abort(403)
    if not target.is_file():
        abort(404)

    if max_side is not None and 32 <= max_side <= 640:
        suf = target.suffix.lower()
        if suf in (".jpg", ".jpeg", ".png", ".webp"):
            try:
                import cv2
            except ImportError:
                cv2 = None  # type: ignore[misc, assignment]
            if cv2 is not None:
                arr = cv2.imread(str(target))
                if arr is not None and arr.size:
                    h, w = arr.shape[:2]
                    longest = max(h, w)
                    if longest > max_side:
                        scale = max_side / float(longest)
                        arr = cv2.resize(
                            arr,
                            (int(w * scale), int(h * scale)),
                            interpolation=cv2.INTER_AREA,
                        )
                    ok, enc = cv2.imencode(
                        ".jpg",
                        arr,
                        (int(cv2.IMWRITE_JPEG_QUALITY), 72),
                    )
                    if ok:
                        return Response(
                            enc.tobytes(),
                            mimetype="image/jpeg",
                            headers={
                                "Cache-Control": "public, max-age=604800",
                            },
                        )

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


# ---------------------------------------------------------------------------
# Training data endpoints
# ---------------------------------------------------------------------------

# In-process cache: key → (results, inference_device) (avoids re-running inference)
_TRAINING_ANALYSIS_CACHE: dict[str, tuple[list[dict], str]] = {}


@bp.get("/missions/<mission_id>/training/frame_count")
def training_frame_count(mission_id: str):
    """How many analyzable JPEGs exist in ``frames/`` (numeric filename stem)."""
    if not mission_id.isdigit():
        abort(400)
    src = request.args.get("src", "rpi")
    mission_dir = _missions_root(src) / mission_id
    if not mission_dir.is_dir():
        abort(404)
    from services.training_data import count_training_frames

    stride_raw = request.args.get("stride", "1").strip()
    stride = int(stride_raw) if stride_raw.isdigit() else 1
    stride = max(1, min(stride, 500))
    n = count_training_frames(mission_dir, stride=stride)
    return jsonify({"ok": True, "n_frames": n, "frame_stride": stride})


@bp.get("/missions/<mission_id>/training/frame_list")
def training_frame_list(mission_id: str):
    """Return sorted list of frame relative paths (``frames/NNNNN.jpg``) for filmstrip previews."""
    if not mission_id.isdigit():
        abort(400)
    src = request.args.get("src", "rpi")
    mission_dir = _missions_root(src) / mission_id
    if not mission_dir.is_dir():
        abort(404)
    from services.training_data import collect_training_frame_files

    all_files = collect_training_frame_files(mission_dir, stride=1)
    paths = [f"frames/{p.name}" for _ts, p in all_files]
    return jsonify({"ok": True, "paths": paths, "total": len(paths)})


@bp.post("/missions/<mission_id>/training/analyze")
def training_analyze(mission_id: str):
    """Run YOLO inference + GPS matching on all frames. Cached per frames-dir mtime.

    Body JSON: {real_mission, conf_thresh, dist_thresh, frame_stride,
 optional model_path (.pt on server), optional batch_size 1–256,
 optional focus_timestamp_ns (int; stream YOLO batches near this frame first),
 optional focus_radius (int 0–2000, default 40; indices each side after stride)}.

    Query ``stream=1``: ``application/x-ndjson`` — one JSON object per line:
 ``meta`` (n_frames), repeated ``batch`` (frames, total_so_far), then ``done`` or ``error``.
    """
    if not mission_id.isdigit():
        abort(400)
    body = request.get_json(silent=True) or {}
    real_mission_name = str(body.get("real_mission", "")).strip()
    conf_thresh = float(body.get("conf_thresh", 0.6))
    dist_thresh = float(body.get("dist_thresh", 80.0))
    stride_raw = body.get("frame_stride", 1)
    try:
        frame_stride = int(stride_raw)
    except (TypeError, ValueError):
        frame_stride = 1
    frame_stride = max(1, min(frame_stride, 500))
    stream_want = request.args.get("stream", "").lower() in ("1", "true", "yes")

    focus_timestamp_ns: int | None = None
    _raw_ft = body.get("focus_timestamp_ns")
    if _raw_ft is not None and _raw_ft != "":
        try:
            focus_timestamp_ns = int(_raw_ft)
        except (TypeError, ValueError):
            focus_timestamp_ns = None
    focus_radius = 40
    _raw_fr = body.get("focus_radius")
    if _raw_fr is not None and _raw_fr != "":
        try:
            focus_radius = max(0, min(2000, int(_raw_fr)))
        except (TypeError, ValueError):
            focus_radius = 40

    if not real_mission_name or "/" in real_mission_name or "\\" in real_mission_name:
        return jsonify({"ok": False, "error": "real_mission filename required"}), 400

    src = request.args.get("src", "rpi")
    missions_root = _missions_root(src)
    mission_dir = missions_root / mission_id
    if not mission_dir.is_dir():
        abort(404)

    log_path = _mission_log(mission_id, src)

    # Load weed locations from real_missions/
    try:
        setup = load_real_mission_setup(real_mission_name)
    except FileNotFoundError:
        return jsonify({"ok": False, "error": f"Setup file not found: {real_mission_name}"}), 404
    weed_locations = setup.get("weed_locations", [])

    from services.training_data import (
        analyze_mission,
        collect_training_frame_files,
        iter_analyze_mission_batches,
        parse_request_batch_size,
        resolve_training_model_path,
        training_analysis_cache_key,
        training_runtime_diagnostics,
        yolo_loaded_device,
        yolo_predict_device_kw,
    )

    try:
        model_path = resolve_training_model_path(body.get("model_path"))
    except FileNotFoundError:
        mp_raw = body.get("model_path")
        hint = str(mp_raw).strip() if mp_raw is not None else ""
        return jsonify(
            {"ok": False, "error": f"YOLO weights not found: {hint or '(empty)'}"}
        ), 400

    yolo_batch: int | None = None
    if "batch_size" in body:
        try:
            yolo_batch = parse_request_batch_size(body.get("batch_size"))
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    cache_key = training_analysis_cache_key(
        mission_dir,
        real_mission_name,
        model_path=model_path,
        conf_thresh=conf_thresh,
        dist_thresh=dist_thresh,
        frame_stride=frame_stride,
        yolo_batch=yolo_batch,
    )
    if cache_key in _TRAINING_ANALYSIS_CACHE:
        results, inference_device = _TRAINING_ANALYSIS_CACHE[cache_key]
        if stream_want:

            def gen_cached():
                n = len(results)
                yield json.dumps(
                    {
                        "type": "meta",
                        "n_frames": n,
                        "frame_stride": frame_stride,
                        "device_override": yolo_predict_device_kw(),
                        "diagnostics": training_runtime_diagnostics(
                            model_path,
                            batch_size=yolo_batch,
                            frame_stride=frame_stride,
                        ),
                    }
                ) + "\n"
                yield json.dumps(
                    {
                        "type": "batch",
                        "frames": results,
                        "total_so_far": n,
                    }
                ) + "\n"
                yield json.dumps(
                    {
                        "type": "done",
                        "ok": True,
                        "inference_device": inference_device,
                        "cached": True,
                        "device_override": yolo_predict_device_kw(),
                    }
                ) + "\n"

            return Response(
                stream_with_context(gen_cached()),
                mimetype="application/x-ndjson",
                headers={
                    "Cache-Control": "no-store",
                    "X-Accel-Buffering": "no",
                    "X-Content-Type-Options": "nosniff",
                },
            )
        return jsonify(
            {
                "ok": True,
                "results": results,
                "cached": True,
                "inference_device": inference_device,
                "device_override": yolo_predict_device_kw(),
            }
        )

    if stream_want:
        n_frames = len(
            collect_training_frame_files(mission_dir, stride=frame_stride)
        )

        def gen_stream():
            acc: list[dict] = []
            try:
                yield json.dumps(
                    {
                        "type": "meta",
                        "n_frames": n_frames,
                        "frame_stride": frame_stride,
                        "device_override": yolo_predict_device_kw(),
                        "diagnostics": training_runtime_diagnostics(
                            model_path,
                            batch_size=yolo_batch,
                            frame_stride=frame_stride,
                        ),
                    }
                ) + "\n"
                for batch in iter_analyze_mission_batches(
                    mission_dir=mission_dir,
                    log_path=log_path,
                    weed_locations=weed_locations,
                    model_path=model_path,
                    conf_thresh=conf_thresh,
                    dist_thresh=dist_thresh,
                    frame_stride=frame_stride,
                    batch_size=yolo_batch,
                    focus_timestamp_ns=focus_timestamp_ns,
                    focus_radius=focus_radius,
                ):
                    acc.extend(batch)
                    yield json.dumps(
                        {
                            "type": "batch",
                            "frames": batch,
                            "total_so_far": len(acc),
                        }
                    ) + "\n"
                inference_device = yolo_loaded_device(model_path)
                _TRAINING_ANALYSIS_CACHE[cache_key] = (acc, inference_device)
                yield json.dumps(
                    {
                        "type": "done",
                        "ok": True,
                        "inference_device": inference_device,
                        "cached": False,
                        "device_override": yolo_predict_device_kw(),
                    }
                ) + "\n"
            except Exception as exc:
                yield json.dumps({"type": "error", "ok": False, "error": str(exc)}) + "\n"

        return Response(
            stream_with_context(gen_stream()),
            mimetype="application/x-ndjson",
            headers={
                "Cache-Control": "no-store",
                "X-Accel-Buffering": "no",
                "X-Content-Type-Options": "nosniff",
            },
        )

    try:
        results, inference_device = analyze_mission(
            mission_dir=mission_dir,
            log_path=log_path,
            weed_locations=weed_locations,
            model_path=model_path,
            conf_thresh=conf_thresh,
            dist_thresh=dist_thresh,
            frame_stride=frame_stride,
            batch_size=yolo_batch,
            focus_timestamp_ns=focus_timestamp_ns,
            focus_radius=focus_radius,
        )
    except RuntimeError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

    _TRAINING_ANALYSIS_CACHE[cache_key] = (results, inference_device)
    device_override = yolo_predict_device_kw()
    return jsonify(
        {
            "ok": True,
            "results": results,
            "cached": False,
            "inference_device": inference_device,
            "device_override": device_override,
        }
    )


@bp.post("/missions/<mission_id>/training/compare_models")
def training_compare_models(mission_id: str):
    """Run YOLO on one frame with multiple weights (default = UI preset lists).

    Body JSON: ``frame_path`` (e.g. ``frames/123.jpg``), optional ``models`` array of
    hub names or server paths. Caps at ``SKYDOCK_TRAINING_COMPARE_MAX_MODELS`` (default 24).
    """
    if not mission_id.isdigit():
        abort(400)
    body = request.get_json(silent=True) or {}
    frame_path = str(body.get("frame_path", "")).strip()
    raw_models = body.get("models")
    src = request.args.get("src", "sim")
    missions_root = _missions_root(src)
    mission_dir = missions_root / mission_id
    if not mission_dir.is_dir():
        abort(404)

    from services.training_data import (
        compare_yolo_models_on_image,
        safe_training_frame_image_path,
        training_compare_default_model_specs,
    )

    abs_img = safe_training_frame_image_path(mission_dir, frame_path)
    if abs_img is None:
        return jsonify({"ok": False, "error": "invalid or missing frame_path"}), 400

    if raw_models is not None:
        if not isinstance(raw_models, list):
            return jsonify({"ok": False, "error": "models must be a JSON array"}), 400
        specs = [str(x).strip() for x in raw_models if str(x).strip()]
    else:
        specs = training_compare_default_model_specs()

    if not specs:
        return jsonify({"ok": False, "error": "no models to compare"}), 400

    try:
        rows = compare_yolo_models_on_image(abs_img, specs)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

    return jsonify({"ok": True, "frame_path": frame_path, "results": rows})


@bp.post("/training/yolo_prefetch")
def training_yolo_prefetch():
    """Download/cache Ultralytics hub weights (``~/.cache/ultralytics``).

    Body JSON optional: ``{"models": ["yolov8n.pt", ...]}``. If omitted, prefetches
    all hub names from training presets (auto-pick + default list + COCO list).
    """
    body = request.get_json(silent=True) or {}
    raw_models = body.get("models")
    from services.training_data import (
        predownload_training_preset_weights,
        predownload_ultralytics_weights,
    )
    if raw_models is not None:
        if not isinstance(raw_models, list):
            return jsonify({"ok": False, "error": "models must be a JSON array"}), 400
        results = predownload_ultralytics_weights([str(x) for x in raw_models])
    else:
        results = predownload_training_preset_weights()
    ok = all(v.get("ok") for v in results.values()) if results else True
    return jsonify({"ok": ok, "results": results})


@bp.post("/missions/<mission_id>/training/save_labels")
def training_save_labels(mission_id: str):
    """Write YOLO .txt label files next to approved frames and save metadata.

    Body JSON: {
        approved: [{timestamp_ns, yolo_bbox: {x1,y1,x2,y2}}, ...],
        skipped: [timestamp_ns, ...],
        thresholds: {conf_thresh, dist_thresh}
    }
    """
    if not mission_id.isdigit():
        abort(400)
    body = request.get_json(silent=True) or {}
    approved = body.get("approved", [])
    skipped = body.get("skipped", [])
    thresholds = body.get("thresholds", {})

    src = request.args.get("src", "rpi")
    missions_root = _missions_root(src)
    mission_dir = missions_root / mission_id
    if not mission_dir.is_dir():
        abort(404)

    from services.training_data import save_labels, write_training_metadata
    try:
        count = save_labels(mission_dir, approved)
        approved_ts = sorted({int(a["timestamp_ns"]) for a in approved})
        skipped_ts = [int(s) for s in skipped]
        write_training_metadata(mission_dir, approved_ts, skipped_ts, thresholds)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

    return jsonify({"ok": True, "labels_written": count, "mission_dir": str(mission_dir)})


@bp.get("/missions/<mission_id>/training/progress")
def training_get_progress(mission_id: str):
    """Return ``training_review_progress.json`` if present (saved review session)."""
    if not mission_id.isdigit():
        abort(400)
    src = request.args.get("src", "rpi")
    mission_dir = _missions_root(src) / mission_id
    if not mission_dir.is_dir():
        abort(404)
    from services.training_data import load_review_progress

    data = load_review_progress(mission_dir)
    if data is None:
        return jsonify({"ok": False, "error": "no_saved_progress"}), 404
    return jsonify({"ok": True, "progress": data})


@bp.post("/missions/<mission_id>/training/save_progress")
def training_save_progress(mission_id: str):
    """Write ``training_review_progress.json`` (body = full JSON document from the UI)."""
    if not mission_id.isdigit():
        abort(400)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"ok": False, "error": "expected JSON object body"}), 400
    src = request.args.get("src", "rpi")
    mission_dir = _missions_root(src) / mission_id
    if not mission_dir.is_dir():
        abort(404)
    from services.training_data import save_review_progress

    try:
        path = save_review_progress(mission_dir, body)
    except (OSError, TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "path": str(path)})


@bp.post("/training/assemble_real_dataset")
def training_assemble_real_dataset():
    """Copy labeled frames from one or more missions into ``ai_train/real_data`` (train/valid + data.yaml).

    Body JSON: ``{mission_ids: ["0042", ...], src: "rpi", dest: null}`` — ``dest`` optional absolute path override.
    """
    body = request.get_json(silent=True) or {}
    raw_ids = body.get("mission_ids")
    if not isinstance(raw_ids, list) or not raw_ids:
        return jsonify({"ok": False, "error": "mission_ids (non-empty list) required"}), 400
    mission_ids = [str(x).strip() for x in raw_ids if str(x).strip()]
    src = str(body.get("src", "rpi")).strip().lower()
    dest_raw = body.get("dest")
    dest: Path | None
    if dest_raw:
        dest = Path(str(dest_raw)).expanduser()
    else:
        dest = None

    missions_root = _missions_root(src if src in ("rpi", "sim") else "rpi")
    from services.training_data import assemble_real_dataset

    try:
        root_str, n = assemble_real_dataset(mission_ids, missions_root, dest)
    except OSError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "dest": root_str, "files_copied": n})


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
