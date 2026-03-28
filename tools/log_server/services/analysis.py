"""Mission log aggregation (JSONL) for API responses."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai_class import Detection
from utils import detection_to_latlon

from services.geometry import grid_dedup, haversine_m, parse_ts
from services.mission_store import iter_events
from services.projection import (
    camera_fov_footprint_from_drone_dict,
    drone_state_from_dict,
    ground_project_list,
)


def weed_prediction_points(path: Path, dedup: bool, thresh_m: float) -> list[dict[str, float]]:
    pts: list[dict[str, float]] = []
    for ev in iter_events(path):
        if ev.get("event") != "weed_detected":
            continue
        lat = ev.get("lat") or (ev.get("weed") or {}).get("lat")
        lon = ev.get("lon") or (ev.get("weed") or {}).get("lon")
        if lat is None or lon is None:
            continue
        pts.append({"lat": float(lat), "lon": float(lon)})
    if dedup:
        pts = grid_dedup(pts, thresh_m)
    return pts


def _normalize_fsm_state_name(raw: str | None) -> str | None:
    """``DroneStateEnum.SCAN`` → ``SCAN`` for stable API / map coloring."""
    if not raw or not isinstance(raw, str):
        return None
    s = raw.strip()
    if "." in s:
        s = s.rsplit(".", 1)[-1]
    u = s.upper()
    return u if u else None


def camera_fov_polygons_from_fsm_ticks(
    path: Path,
    stride: int,
    states_filter: frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    """One camera FOV quadrilateral per ``fsm_tick`` (``drone_state`` at control-loop rate, often ~30–50 Hz).

    ``telemetry_sample`` is logged ~1 Hz in the vehicle logger, so it is **not** used here — that made the map
    look far too sparse. Same projection as ``frame_footprint`` / ``utils.detection_to_latlon``.
    Each row includes ``state`` (normalized, e.g. ``SCAN``) for map coloring. Optional ``states_filter`` keeps
    only those modes (uppercase names, comma-separated in the API).
    """
    out: list[dict[str, Any]] = []
    count = 0
    for ev in iter_events(path):
        if ev.get("event") != "fsm_tick":
            continue
        count += 1
        if stride > 1 and (count % stride) != 0:
            continue
        st = _normalize_fsm_state_name(ev.get("state"))
        if states_filter is not None and (st is None or st not in states_filter):
            continue
        ds = ev.get("drone_state")
        fp = camera_fov_footprint_from_drone_dict(ds if isinstance(ds, dict) else None)
        if not fp:
            continue
        d = ds if isinstance(ds, dict) else {}
        row: dict[str, Any] = {
            "ts": ev.get("ts"),
            "footprint": fp,
            "lat": float(d.get("latitude") or 0.0),
            "lon": float(d.get("longitude") or 0.0),
        }
        if st:
            row["state"] = st
        out.append(row)
    return out


def telemetry_path_points(path: Path, stride: int) -> list[dict[str, Any]]:
    pts: list[dict[str, Any]] = []
    count = 0
    for ev in iter_events(path):
        if ev.get("event") != "telemetry_sample":
            continue
        count += 1
        if count % stride != 0:
            continue
        ds = ev.get("drone_state", {})
        lat, lon = ds.get("latitude", 0), ds.get("longitude", 0)
        if lat == 0 and lon == 0:
            continue
        pts.append({"lat": lat, "lon": lon, "alt": ds.get("altitude_rel_home", 0), "ts": ev.get("ts", "")})
    return pts


def build_timeline_payload(path: Path) -> dict[str, Any]:
    transitions: list[dict[str, Any]] = []
    last_ts = None
    for ev in iter_events(path):
        ts = parse_ts(ev.get("ts", ""))
        if ts > 0:
            last_ts = ts
        if ev.get("event") == "fsm_transition":
            transitions.append({
                "ts": ts,
                "state_from": ev.get("state_from", "").replace("DroneStateEnum.", ""),
                "state_to": ev.get("state_to", "").replace("DroneStateEnum.", ""),
            })

    segments: list[dict[str, Any]] = []
    visit_counts: dict[str, int] = {}
    for i, t in enumerate(transitions):
        state = t["state_to"]
        start_ts = t["ts"]
        end_ts = transitions[i + 1]["ts"] if i + 1 < len(transitions) else (last_ts or start_ts)
        visit_counts[state] = visit_counts.get(state, 0) + 1
        segments.append({
            "state": state,
            "start_ts": start_ts,
            "end_ts": end_ts,
            "duration_s": max(0.0, end_ts - start_ts),
            "visit_num": visit_counts[state],
        })

    summary: dict[str, dict[str, Any]] = {}
    for seg in segments:
        s = seg["state"]
        if s not in summary:
            summary[s] = {"state": s, "total_s": 0.0, "visits": 0}
        summary[s]["total_s"] += seg["duration_s"]
        summary[s]["visits"] += 1

    return {
        "segments": segments,
        "summary": sorted(summary.values(), key=lambda x: -x["total_s"]),
    }


def build_summary_payload(path: Path) -> dict[str, Any]:
    header: dict[str, Any] = {}
    event_counts: dict[str, int] = {}
    first_ts = last_ts = None
    weed_pts: list[dict[str, float]] = []
    spray_n = 0
    n_lines = 0
    frames_with_detections = 0
    prev_ll: tuple[float, float] | None = None
    path_length_m = 0.0
    alts: list[float] = []

    for ev in iter_events(path):
        n_lines += 1
        ev_type = ev.get("event", "")
        event_counts[ev_type] = event_counts.get(ev_type, 0) + 1
        ts = parse_ts(ev.get("ts", ""))
        if ts > 0:
            if first_ts is None:
                first_ts = ts
            last_ts = ts
        if ev_type == "mission_start":
            header = ev
        if ev_type == "weed_detected":
            lat = (ev.get("weed") or {}).get("lat")
            lon = (ev.get("weed") or {}).get("lon")
            if lat and lon:
                weed_pts.append({"lat": float(lat), "lon": float(lon)})
        if ev_type in ("weed_sprayed", "spray_attempt"):
            spray_n += 1
        fr = ev.get("frame")
        if fr and (fr.get("detections") or []):
            frames_with_detections += 1
        if ev_type == "telemetry_sample":
            ds = ev.get("drone_state") or {}
            lat, lon = ds.get("latitude"), ds.get("longitude")
            if lat is not None and lon is not None:
                la, lo = float(lat), float(lon)
                if not (la == 0.0 and lo == 0.0):
                    if prev_ll is not None:
                        path_length_m += haversine_m(prev_ll[0], prev_ll[1], la, lo)
                    prev_ll = (la, lo)
                alt = ds.get("altitude_rel_home")
                if alt is not None:
                    try:
                        alts.append(float(alt))
                    except (TypeError, ValueError):
                        pass

    duration_s = (last_ts - first_ts) if first_ts and last_ts else 0.0
    unique_weeds = len(grid_dedup(weed_pts, 0.5))

    sim_truth_raw = header.get("sim_truth_file")
    sim_truth_file = Path(str(sim_truth_raw)).name if sim_truth_raw else None

    alt_min = min(alts) if alts else None
    alt_max = max(alts) if alts else None
    alt_mean = sum(alts) / len(alts) if alts else None
    db_writes = {k: v for k, v in event_counts.items() if k.startswith("db_")}

    insights = {
        "log_file_bytes": path.stat().st_size,
        "jsonl_lines": n_lines,
        "telemetry_samples": event_counts.get("telemetry_sample", 0),
        "fsm_ticks": event_counts.get("fsm_tick", 0),
        "fsm_transitions": event_counts.get("fsm_transition", 0),
        "move_commands": event_counts.get("move_command", 0),
        "frames_with_detections": frames_with_detections,
        "path_length_m": round(path_length_m, 2),
        "altitude_rel_m_min": round(alt_min, 3) if alt_min is not None else None,
        "altitude_rel_m_max": round(alt_max, 3) if alt_max is not None else None,
        "altitude_rel_m_mean": round(alt_mean, 3) if alt_mean is not None else None,
        "db_writes": db_writes,
    }

    return {
        "header": header,
        "duration_s": duration_s,
        "event_counts": event_counts,
        "weed_detections": len(weed_pts),
        "unique_weeds": unique_weeds,
        "spray_events": spray_n,
        "sim_truth_file": sim_truth_file,
        "insights": insights,
    }


def tail_json_events(path: Path, since_byte: int) -> dict[str, Any]:
    file_size = path.stat().st_size
    if since_byte >= file_size:
        return {"events": [], "next_byte": file_size, "file_size": file_size}

    with open(path, "rb") as f:
        f.seek(since_byte)
        chunk = f.read()

    last_nl = chunk.rfind(b"\n")
    if last_nl == -1:
        return {"events": [], "next_byte": since_byte, "file_size": file_size}

    complete = chunk[: last_nl + 1]
    next_byte = since_byte + len(complete)

    events: list[Any] = []
    for raw in complete.split(b"\n"):
        raw = raw.strip()
        if not raw:
            continue
        try:
            events.append(json.loads(raw.decode("utf-8", errors="replace")))
        except json.JSONDecodeError:
            pass

    return {"events": events, "next_byte": next_byte, "file_size": file_size}


def build_frame_events(path: Path) -> list[dict[str, Any]]:
    """Build frame rows for ``GET .../frame_events`` (Map tab BBox ground layer).

    Emits one object per log line that has ``frame`` with a non-empty ``detections``
    list. Each row includes ``ground_projections``, ``frame_footprint`` (camera corners),
    and ``ground_projection_note`` when projection was skipped — see
    ``services.projection.ground_project_list`` (needs ``drone_state`` and
    ``altitude_rel_home`` > 0 on the same line as the frame).
    """
    results: list[dict[str, Any]] = []
    for ev in iter_events(path):
        frame = ev.get("frame")
        if not frame:
            continue
        dets = frame.get("detections") or []
        if not dets:
            continue
        raw_dets = frame.get("raw_detections")
        ds_obj = drone_state_from_dict(ev.get("drone_state"))
        g_logged, g_note = ground_project_list(dets, ds_obj)
        g_raw: list[dict] | None = None
        g_raw_note: str | None = None
        if raw_dets:
            g_raw, g_raw_note = ground_project_list(raw_dets, ds_obj)
        note = g_note or g_raw_note

        footprint: list[dict[str, float]] = []
        if ds_obj and ds_obj.altitude_rel_home > 0:
            w, h = 640, 640
            for u, v in [(0, 0), (w, 0), (w, h), (0, h)]:
                try:
                    pt = Detection(label="", confidence=0.0, bbox=[(u, v), (u, v)])
                    la, lo = detection_to_latlon(ds_obj, pt)
                    footprint.append({"lat": float(la), "lon": float(lo)})
                except Exception:
                    pass

        drone_pos = None
        if ds_obj:
            drone_pos = {"lat": ds_obj.latitude, "lon": ds_obj.longitude}

        results.append({
            "frame_index": len(results),
            "ts": ev.get("ts"),
            "event": ev.get("event"),
            "state_from": (ev.get("state_from") or "").replace("DroneStateEnum.", ""),
            "state_to": (ev.get("state_to") or "").replace("DroneStateEnum.", ""),
            "photo_path": frame.get("photo_path", ""),
            "detections": dets,
            "raw_detections": raw_dets if raw_dets else None,
            "drone_state": ev.get("drone_state"),
            "ground_projections": g_logged,
            "raw_ground_projections": g_raw if raw_dets else None,
            "ground_projection_note": note,
            "frame_footprint": footprint,
            "drone_pos": drone_pos,
        })
    return results


def latest_sim_vision_event(path: Path) -> dict[str, Any] | None:
    latest = None
    for ev in iter_events(path):
        if ev.get("event") == "sim_vision_params":
            latest = ev
    return latest


def sim_compare_payload(
    mission_log: Path,
    sim_data_root: Path,
    truth_name: str,
    thresh_m: float,
) -> dict[str, Any]:
    truth_path = sim_data_root / truth_name
    data = json.loads(truth_path.read_text(encoding="utf-8"))
    raw_weeds = data.get("weed_locations", [])
    truth: list[dict[str, Any]] = []
    for i, w in enumerate(raw_weeds):
        if isinstance(w, dict):
            truth.append({"id": w.get("id", i), "lat": float(w["lat"]), "lon": float(w["lon"])})
        else:
            truth.append({"id": i, "lat": float(w[0]), "lon": float(w[1])})

    pred = weed_prediction_points(mission_log, dedup=True, thresh_m=thresh_m)

    used: set[int] = set()
    tp = fp = 0
    for pr in pred:
        best_i, best_d = None, float("inf")
        for i, t in enumerate(truth):
            if i in used:
                continue
            d = haversine_m(pr["lat"], pr["lon"], t["lat"], t["lon"])
            if d < best_d:
                best_d, best_i = d, i
        if best_i is not None and best_d <= thresh_m:
            tp += 1
            used.add(best_i)
        else:
            fp += 1
    fn = len(truth) - len(used)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0

    return {
        "truth_points": truth,
        "stats": {
            "truth": len(truth),
            "pred": len(pred),
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": precision,
            "recall": recall,
            "thresh_m": thresh_m,
        },
    }
