"""Mission log aggregation (JSONL) for API responses."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from ai_class import Detection
from utils import detection_to_latlon

from services.geometry import grid_dedup, haversine_m, parse_ts
from services.mission_cache import MISSION_READ_CACHE
from services.mission_store import iter_events, iter_events_of_kind
from services.projection import (
    camera_fov_footprint_from_drone_dict,
    drone_state_from_dict,
    ground_project_list,
)
MIN_NUM_DET = 3
MIN_WEED_SPACING = 2


def _log_rev_key(path: Path) -> tuple[str, int, int]:
    st = path.stat()
    return (str(path.resolve()), st.st_mtime_ns, st.st_size)


def _frames_dir_rev(mission_dir: Path | None) -> int:
    """Change when JPEGs under ``mission_dir/frames/`` change (for ``build_frame_events`` cache)."""
    if mission_dir is None:
        return 0
    fd = mission_dir / "frames"
    if not fd.is_dir():
        return 0
    try:
        return max((f.stat().st_mtime_ns for f in fd.iterdir() if f.is_file()), default=0)
    except OSError:
        return 0


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


def weed_prediction_points_from_detections(
    path: Path,
    *,
    spacing_m: float,
    min_num_det: int,
) -> list[dict[str, float]]:
    """
    Recompute predicted weed points by reclustering projected detection centers.

    This reclustering mirrors the intent of `states/scan.py::prosess_all_scan_data()`:
    - project `frame.detections[]` bbox centers to (lat, lon)
    - add a detection to the nearest cluster if distance < `spacing_m`
    - otherwise create a new cluster
    - keep only clusters with `count >= min_num_det`

    Returns: `[{lat, lon}, ...]` (no grid-dedup applied here).
    """
    st = path.stat()
    cache_key = ("weed_det", str(path.resolve()), st.st_mtime_ns, st.st_size, float(spacing_m), int(min_num_det))
    cached = MISSION_READ_CACHE.get(cache_key)
    if cached is not None:
        return cached

    spacing_m = float(spacing_m)
    min_num_det = int(min_num_det)
    if min_num_det <= 0:
        min_num_det = 1

    # Each cluster stores running sums to output avg location.
    clusters: list[dict[str, float]] = []  # {"lat_sum":..., "lon_sum":..., "n":...}

    for ev in iter_events_of_kind(path, "fsm_tick"):
        frame = ev.get("frame")
        if not isinstance(frame, dict):
            continue
        dets = frame.get("detections") or []
        if not isinstance(dets, list) or not dets:
            continue

        ds_dict = ev.get("drone_state")
        if not isinstance(ds_dict, dict):
            continue
        ds_obj = drone_state_from_dict(ds_dict)
        if ds_obj is None:
            continue

        for det in dets:
            if not isinstance(det, dict):
                continue
            bbox = det.get("bbox")
            if not bbox or not isinstance(bbox, list) or len(bbox) < 2:
                continue
            try:
                p0, p1 = bbox[0], bbox[1]
                x0, y0 = float(p0[0]), float(p0[1])
                x1, y1 = float(p1[0]), float(p1[1])
            except Exception:
                continue

            # Project bbox center to ground lat/lon via the repo geometry helpers.
            label = str(det.get("label") or "")
            conf = det.get("confidence")
            try:
                conf_f = float(conf) if conf is not None else 0.0
            except Exception:
                conf_f = 0.0

            d_obj = Detection(label=label, confidence=conf_f, bbox=[(x0, y0), (x1, y1)])
            try:
                la, lo = detection_to_latlon(ds_obj, d_obj)
                la = float(la)
                lo = float(lo)
            except Exception:
                continue

            if not clusters:
                clusters.append({"lat_sum": la, "lon_sum": lo, "n": 1.0})
                continue

            best_i = 0
            best_d = float("inf")
            for i, c in enumerate(clusters):
                ca_lat = c["lat_sum"] / c["n"]
                ca_lon = c["lon_sum"] / c["n"]
                d = haversine_m(ca_lat, ca_lon, la, lo)
                if d < best_d:
                    best_d = d
                    best_i = i

            if best_d < spacing_m:
                c = clusters[best_i]
                c["lat_sum"] += la
                c["lon_sum"] += lo
                c["n"] += 1.0
            else:
                clusters.append({"lat_sum": la, "lon_sum": lo, "n": 1.0})

    out: list[dict[str, float]] = []
    for c in clusters:
        if int(c["n"]) >= min_num_det:
            out.append(
                {"lat": float(c["lat_sum"] / c["n"]), "lon": float(c["lon_sum"] / c["n"])}
            )

    MISSION_READ_CACHE.set(cache_key, out)
    return out


def build_setup_scan_path(
    weed_locations: list[dict[str, Any]],
    lane_step_m: float = 8.0,
    pad_m: float = 3.0,
) -> list[list[float]]:
    """Build a simple boustrophedon scan path around weeds: [[lat, lon], ...]."""
    pts: list[tuple[float, float]] = []
    for w in weed_locations or []:
        try:
            pts.append((float(w["lat"]), float(w["lon"])))
        except (KeyError, TypeError, ValueError):
            continue
    if not pts:
        return []
    lats = [p[0] for p in pts]
    lons = [p[1] for p in pts]
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)
    center_lat = (min_lat + max_lat) * 0.5
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = max(1.0, 111_320.0 * abs(math.cos(math.radians(center_lat))))
    pad_lat = pad_m / m_per_deg_lat
    pad_lon = pad_m / m_per_deg_lon
    min_lat -= pad_lat
    max_lat += pad_lat
    min_lon -= pad_lon
    max_lon += pad_lon
    lat_step = max(0.5, lane_step_m) / m_per_deg_lat
    n_lanes = max(2, int((max_lat - min_lat) / lat_step) + 1)
    out: list[list[float]] = []
    for i in range(n_lanes):
        la = min_lat + i * lat_step
        if la > max_lat:
            la = max_lat
        if i % 2 == 0:
            out.append([la, min_lon])
            out.append([la, max_lon])
        else:
            out.append([la, max_lon])
            out.append([la, min_lon])
    return out


def _normalize_fsm_state_name(raw: str | None) -> str | None:
    """``DroneStateEnum.SCAN`` → ``SCAN`` for stable API / map coloring."""
    if not raw or not isinstance(raw, str):
        return None
    s = raw.strip()
    if "." in s:
        s = s.rsplit(".", 1)[-1]
    u = s.upper()
    return u if u else None


def _subsample_polygon_rows(rows: list[dict[str, Any]], max_n: int) -> list[dict[str, Any]]:
    """Evenly subsample rows so at most ``max_n`` polygons (keeps spread across the mission)."""
    n = len(rows)
    if n <= max_n or max_n <= 0:
        return rows
    if max_n == 1:
        return [rows[n // 2]]
    out: list[dict[str, Any]] = []
    for j in range(max_n):
        idx = min(n - 1, int(j * (n - 1) // (max_n - 1)))
        out.append(rows[idx])
    return out


def camera_fov_polygons_from_fsm_ticks(
    path: Path,
    stride: int,
    states_filter: frozenset[str] | None = None,
    max_polygons: int | None = None,
) -> tuple[list[dict[str, Any]], bool, int]:
    """One camera FOV quadrilateral per ``fsm_tick`` (``drone_state`` at control-loop rate, often ~30–50 Hz).

    ``telemetry_sample`` is logged ~1 Hz in the vehicle logger, so it is **not** used here — that made the map
    look far too sparse. Same projection as ``frame_footprint`` / ``utils.detection_to_latlon``.
    Each row includes ``state`` (normalized, e.g. ``SCAN``) for map coloring. Optional ``states_filter`` keeps
    only those modes (uppercase names, comma-separated in the API).

    If ``max_polygons`` is a positive integer and more rows match, they are evenly subsampled.
    ``None`` or ``<= 0`` means no cap. Returns ``(polygons, was_capped, count_before_cap)``.
    """
    out: list[dict[str, Any]] = []
    first_added = False
    last_row: dict[str, Any] | None = None
    last_tick_index: int | None = None
    last_added_tick_index: int | None = None
    count = 0
    for ev in iter_events_of_kind(path, "fsm_tick"):
        count += 1
        st = _normalize_fsm_state_name(ev.get("state"))
        if states_filter is not None and (st is None or st not in states_filter):
            continue
        ds = ev.get("drone_state")
        fp = camera_fov_footprint_from_drone_dict(ds if isinstance(ds, dict) else None)
        if not fp:
            continue
        d = ds if isinstance(ds, dict) else {}

        # Save last valid row regardless of sampling, then append it at the end
        # so "every Nth tick" still shows the very first and very last footprints.
        row: dict[str, Any] = {
            "ts": ev.get("ts"),
            "footprint": fp,
            "lat": float(d.get("latitude") or 0.0),
            "lon": float(d.get("longitude") or 0.0),
        }
        tn = ev.get("time_ns")
        if tn is not None:
            try:
                row["time_ns"] = int(tn)
            except (TypeError, ValueError):
                pass
        row["_tick_index"] = count  # internal: used to de-dup first/last sampling endpoints
        if st:
            row["state"] = st

        # Sampling: include the first valid match, then every Nth tick thereafter.
        # The last valid match is appended after the loop (so it is always included).
        if stride <= 1:
            out.append(row)
            first_added = True
            last_added_tick_index = count
        else:
            if not first_added:
                out.append(row)
                first_added = True
                last_added_tick_index = count
            elif (count % stride) == 0:
                out.append(row)
                last_added_tick_index = count

        last_row = row
        last_tick_index = count
    raw_n = len(out)
    # Ensure the final valid tick is present even if it doesn't land on an "every Nth" boundary.
    if last_row is not None and (last_added_tick_index != last_tick_index):
        out.append(last_row)
        raw_n = len(out)
    if max_polygons is None or max_polygons <= 0 or raw_n <= max_polygons:
        return out, False, raw_n
    capped = _subsample_polygon_rows(out, max_polygons)
    return capped, True, raw_n


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


def fsm_tick_path_points(path: Path, stride: int) -> list[dict[str, Any]]:
    """GPS path from ``fsm_tick`` drone_state — same state stream as camera / bbox projection (aligns with overlays)."""
    rev = _log_rev_key(path)
    cache_key = ("fsm_path", *rev, int(stride))
    cached = MISSION_READ_CACHE.get(cache_key)
    if cached is not None:
        return cached

    pts: list[dict[str, Any]] = []
    first_added = False
    last_point: dict[str, Any] | None = None
    last_tick_index: int | None = None
    last_added_tick_index: int | None = None
    count = 0
    for ev in iter_events_of_kind(path, "fsm_tick"):
        count += 1
        ds = ev.get("drone_state", {})
        if not isinstance(ds, dict):
            continue
        lat, lon = ds.get("latitude", 0), ds.get("longitude", 0)
        try:
            la, lo = float(lat), float(lon)
        except (TypeError, ValueError):
            continue
        if la == 0.0 and lo == 0.0:
            continue

        # Build and save last valid point regardless of sampling; append it after the loop
        # so "every Nth tick" sampling always includes the last point.
        row = {
            "lat": la,
            "lon": lo,
            "alt": ds.get("altitude_rel_home", 0),
            "ts": ev.get("ts", ""),
            "state": ev.get("state", ""),
            "_tick_index": count,  # internal: used to de-dup endpoints
        }

        if stride <= 1:
            pts.append(row)
            first_added = True
            last_added_tick_index = count
        else:
            if not first_added:
                pts.append(row)
                first_added = True
                last_added_tick_index = count
            elif (count % stride) == 0:
                pts.append(row)
                last_added_tick_index = count

        last_point = row
        last_tick_index = count

    if last_point is not None and (last_added_tick_index != last_tick_index):
        pts.append(last_point)
    MISSION_READ_CACHE.set(cache_key, pts)
    return pts


def build_timeline_payload(path: Path) -> dict[str, Any]:
    rev = _log_rev_key(path)
    cached = MISSION_READ_CACHE.get(("timeline", *rev))
    if cached is not None:
        return cached

    transitions: list[dict[str, Any]] = []
    last_ts = None
    for ev in iter_events(path):
        ts = parse_ts(ev.get("ts", ""))
        if ts > 0:
            last_ts = ts
        if ev.get("event") == "fsm_transition":
            transitions.append({
                "ts": ts,
                "state_from": ev.get("state_from", ""),
                "state_to": ev.get("state_to", ""),
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

    out = {
        "segments": segments,
        "summary": sorted(summary.values(), key=lambda x: -x["total_s"]),
    }
    MISSION_READ_CACHE.set(("timeline", *rev), out)
    return out


def build_summary_payload(path: Path) -> dict[str, Any]:
    rev = _log_rev_key(path)
    cached = MISSION_READ_CACHE.get(("summary", *rev))
    if cached is not None:
        return cached

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
        if ev_type in ("db_weed_sprayed", "spray_attempt"):
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

    # Defaults used by the in-run `prosess_all_scan_data()` clustering in `states/scan.py`.
    # Mission logs currently store `weed_match_m`, but not the clustering constants; we expose
    # these code defaults so the UI can show an "Actual (default)" marker next to sliders.
    if header is not None and isinstance(header, dict):
        header.setdefault("min_weed_spacing_m_default", float(MIN_WEED_SPACING))
        header.setdefault("min_num_det_default", int(MIN_NUM_DET))

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

    payload = {
        "header": header,
        "duration_s": duration_s,
        "event_counts": event_counts,
        "weed_detections": len(weed_pts),
        "unique_weeds": unique_weeds,
        "spray_events": spray_n,
        "sim_truth_file": sim_truth_file,
        "insights": insights,
    }
    MISSION_READ_CACHE.set(("summary", *rev), payload)
    return payload


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


def _nearest_by_ts(sorted_entries: list[tuple[int, Any]], ts_ns: int) -> Any | None:
    """Binary-search for the entry with the closest timestamp to ``ts_ns``."""
    from bisect import bisect_right
    if not sorted_entries:
        return None
    keys = [e[0] for e in sorted_entries]
    idx = bisect_right(keys, ts_ns) - 1
    if idx < 0:
        idx = 0
    # Also check idx+1 in case it's closer
    if idx + 1 < len(sorted_entries):
        if abs(sorted_entries[idx + 1][0] - ts_ns) < abs(sorted_entries[idx][0] - ts_ns):
            idx += 1
    return sorted_entries[idx][1]


def _make_frame_row(
    frame_index: int,
    photo_path: str,
    dets: list,
    raw_dets: list | None,
    drone_state_dict: dict | None,
    ts_str: str | None,
    event_name: str,
    state_from: str,
    state_to: str,
) -> dict[str, Any]:
    ds_obj = drone_state_from_dict(drone_state_dict)
    g_logged, g_note = ground_project_list(dets, ds_obj)
    g_raw: list[dict] | None = None
    g_raw_note: str | None = None
    if raw_dets:
        g_raw, g_raw_note = ground_project_list(raw_dets, ds_obj)
    note = g_note or g_raw_note

    footprint: list[dict[str, float]] = []
    if ds_obj and ds_obj.altitude_rel_home > 0:
        w, h = ds_obj.width, ds_obj.hight
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

    return {
        "frame_index": frame_index,
        "ts": ts_str,
        "event": event_name,
        "state_from": state_from,
        "state_to": state_to,
        "photo_path": photo_path,
        "detections": dets,
        "raw_detections": raw_dets if raw_dets else None,
        "drone_state": drone_state_dict,
        "ground_projections": g_logged,
        "raw_ground_projections": g_raw if raw_dets else None,
        "ground_projection_note": note,
        "frame_footprint": footprint,
        "drone_pos": drone_pos,
    }


def build_frame_events(path: Path, mission_dir: Path | None = None) -> list[dict[str, Any]]:
    """Build frame rows for ``GET .../frame_events``.

    For sim missions the data lives in the JSONL (``frame`` sub-object with
    ``photo_path`` and ``detections``).

    For real missions ``photo_path`` is ``"No photo taken"`` but JPEG files
    exist under ``mission_dir/frames/{timestamp_ns}.jpg``.  When that
    directory has files we scan it, match each JPEG to the nearest
    ``fsm_tick`` by ``time_ns``, and emit one row per frame image — including
    frames with no detections so the full flight is browsable.
    """
    rev = _log_rev_key(path)
    mdir_s = str(mission_dir.resolve()) if mission_dir is not None else ""
    fr_rev = _frames_dir_rev(mission_dir)
    # v3: real-mission detections now matched to jpeg by time_detected (not nearest tick).
    fe_key = ("frame_events", 3, *rev, mdir_s, fr_rev)
    cached = MISSION_READ_CACHE.get(fe_key)
    if cached is not None:
        return cached

    # Check whether to use timestamp-based matching from frames/ directory
    frames_dir = (mission_dir / "frames") if mission_dir else None
    use_frames_dir = False
    frame_files: list[tuple[int, str]] = []  # (ts_ns, relative_path)

    if frames_dir and frames_dir.is_dir():
        for f in frames_dir.iterdir():
            if f.suffix.lower() in (".jpg", ".jpeg") and f.stem.isdigit():
                frame_files.append((int(f.stem), f"frames/{f.name}"))
        if frame_files:
            frame_files.sort()
            use_frames_dir = True

    if use_frames_dir:
        # Build sorted lookup of fsm_tick events by time_ns (for drone_state fallback by jpeg ts).
        ticks: list[tuple[int, dict[str, Any]]] = []
        # Per-jpeg dets index keyed on detection.time_detected (== jpeg stem when AI logged the same frame).
        # One tick can carry detections from a previous AI frame; matching on time_detected avoids
        # cross-attributing detections to the wrong jpeg.
        dets_by_stem: dict[int, tuple[list, dict[str, Any]]] = {}
        for ev in iter_events(path):
            if ev.get("event") != "fsm_tick":
                continue
            time_ns = ev.get("time_ns")
            if time_ns is None:
                continue
            ticks.append((int(time_ns), ev))
            fr = ev.get("frame") or {}
            dets = fr.get("detections") or []
            if not dets:
                continue
            grouped: dict[int, list] = {}
            for d in dets:
                td = d.get("time_detected")
                if td is None:
                    continue
                try:
                    td_i = int(td)
                except (TypeError, ValueError):
                    continue
                grouped.setdefault(td_i, []).append(d)
            for stem, dlist in grouped.items():
                # Last writer wins if two ticks reference the same stem (rare; later tick is closer).
                dets_by_stem[stem] = (dlist, ev)
        ticks.sort(key=lambda x: x[0])

        results: list[dict[str, Any]] = []
        for ts_ns, rel_path in frame_files:
            stem_hit = dets_by_stem.get(ts_ns)
            ev = stem_hit[1] if stem_hit else _nearest_by_ts(ticks, ts_ns)
            if ev is None:
                drone_state_dict = None
                dets = []
                ts_str = None
                state_from = ""
                state_to = ""
            else:
                drone_state_dict = ev.get("drone_state")
                if stem_hit:
                    dets = stem_hit[0]
                else:
                    fr = ev.get("frame") or {}
                    dets = fr.get("detections") or []
                ts_str = ev.get("ts")
                state_from = ev.get("state_from", "")
                state_to = ev.get("state_to", "") or ev.get("state", "")
            results.append(_make_frame_row(
                frame_index=len(results),
                photo_path=rel_path,
                dets=dets,
                raw_dets=None,
                drone_state_dict=drone_state_dict,
                ts_str=ts_str,
                event_name="fsm_tick",
                state_from=state_from,
                state_to=state_to,
            ))
        MISSION_READ_CACHE.set(fe_key, results)
        return results

    # Existing path: JSONL frames with embedded photo_path and detections (sim missions)
    results = []
    for ev in iter_events(path):
        frame = ev.get("frame")
        if not frame:
            continue
        dets = frame.get("detections") or []
        if not dets:
            continue
        raw_dets = frame.get("raw_detections")
        results.append(_make_frame_row(
            frame_index=len(results),
            photo_path=frame.get("photo_path", ""),
            dets=dets,
            raw_dets=raw_dets,
            drone_state_dict=ev.get("drone_state"),
            ts_str=ev.get("ts"),
            event_name=ev.get("event", ""),
            state_from=ev.get("state_from", ""),
            state_to=ev.get("state_to", ""),
        ))
    MISSION_READ_CACHE.set(fe_key, results)
    return results


def latest_sim_vision_event(path: Path) -> dict[str, Any] | None:
    latest = None
    for ev in iter_events(path):
        if ev.get("event") == "sim_vision_params":
            latest = ev
    return latest


def resolve_truth_json_path(sim_data_root: Path, truth_name: str) -> Path | None:
    """Ground-truth JSON: prefer ``sim_data/<name>``, else ``<repo>/real_missions/<name>``."""
    safe = Path(truth_name).name
    if not safe or safe != truth_name:
        return None
    p = sim_data_root / safe
    if p.is_file():
        return p
    p2 = Path(__file__).resolve().parents[3] / "real_missions" / safe
    if p2.is_file():
        return p2
    return None


def sim_compare_payload(
    mission_log: Path,
    truth_path: Path,
    thresh_m: float,
    *,
    spacing_m: float | None = None,
    min_num_det: int | None = None,
) -> dict[str, Any]:
    data = json.loads(truth_path.read_text(encoding="utf-8"))
    raw_weeds = data.get("weed_locations", [])
    truth: list[dict[str, Any]] = []
    for i, w in enumerate(raw_weeds):
        if isinstance(w, dict):
            truth.append({"id": w.get("id", i), "lat": float(w["lat"]), "lon": float(w["lon"])})
        else:
            truth.append({"id": i, "lat": float(w[0]), "lon": float(w[1])})

    if spacing_m is not None and min_num_det is not None:
        # Recluster from raw detections, then apply the same match-radius grid dedup
        # used by the legacy "weed_detected" path.
        pred = weed_prediction_points_from_detections(
            mission_log, spacing_m=spacing_m, min_num_det=min_num_det
        )
        pred = grid_dedup(pred, thresh_m)
    else:
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
