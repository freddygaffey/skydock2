import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


_lock = threading.RLock()
_mission_dir: Optional[Path] = None
_mission_log_path: Optional[Path] = None
_initialized_header: bool = False


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def allocate_mission_dir(
    project_root: Path,
    missions_dir_name: str = "missions",
    counter_filename: str = ".next_mission_id",
    pad: int = 4,
) -> Path:
    missions_root = project_root / missions_dir_name
    missions_root.mkdir(parents=True, exist_ok=True)

    counter_path = missions_root / counter_filename

    def scan_next() -> int:
        max_id = 0
        for p in missions_root.iterdir():
            if not p.is_dir():
                continue
            if p.name.isdigit():
                try:
                    max_id = max(max_id, int(p.name))
                except ValueError:
                    pass
        return max_id + 1 if max_id > 0 else 1

    next_id: Optional[int] = None
    if counter_path.exists():
        try:
            raw = counter_path.read_text(encoding="utf-8").strip()
            if raw:
                next_id = int(raw)
        except Exception:
            next_id = None

    if next_id is None or next_id <= 0:
        next_id = scan_next()

    # Avoid collisions if folders were created without updating counter
    while (missions_root / f"{next_id:0{pad}d}").exists():
        next_id += 1

    mission_dir = missions_root / f"{next_id:0{pad}d}"
    mission_dir.mkdir(parents=True, exist_ok=False)

    # Persist next value (best-effort)
    try:
        counter_path.write_text(str(next_id + 1), encoding="utf-8")
    except Exception:
        pass

    return mission_dir


def configure_mission_dir(mission_dir: Path) -> None:
    global _mission_dir, _mission_log_path, _initialized_header
    with _lock:
        _mission_dir = Path(mission_dir)
        _mission_log_path = _mission_dir / "mission.jsonl"
        _initialized_header = False


def init_mission_log(
    *,
    schema_version: int = 1,
    is_sim: bool = False,
    truth_file: Optional[str] = None,
    weed_match_m: Optional[float] = None,
    min_spray_error_m: Optional[float] = None,
    password_protected_ui: bool = True,
) -> Path:
    """
    Ensure mission.jsonl exists and begins with a mission_start header record.
    Safe to call multiple times.
    """
    global _initialized_header
    with _lock:
        if _mission_dir is None or _mission_log_path is None:
            raise RuntimeError("Mission dir not configured. Call configure_mission_dir() first.")

        _mission_log_path.parent.mkdir(parents=True, exist_ok=True)
        existed = _mission_log_path.exists()
        size = _mission_log_path.stat().st_size if existed else 0
        if size > 0:
            _initialized_header = True
            return _mission_log_path

        header: dict[str, Any] = {
            "ts": _utc_iso(),
            "level": "INFO",
            "logger": "main",
            "event": "mission_start",
            "schema_version": schema_version,
            "mission_id": _mission_dir.name,
            "is_sim": bool(is_sim),
        }
        if truth_file:
            header["sim_truth_file"] = truth_file
        if weed_match_m is not None:
            header["weed_match_m"] = float(weed_match_m)
        if min_spray_error_m is not None:
            header["min_spray_error_m"] = float(min_spray_error_m)
        header["ui_password_enabled"] = bool(password_protected_ui)

        _append_locked(header)
        _initialized_header = True
        return _mission_log_path


def get_mission_dir() -> Optional[Path]:
    return _mission_dir


def get_mission_log_path() -> Optional[Path]:
    return _mission_log_path


def _jsonable(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, (list, tuple, set)):
        return [_jsonable(v) for v in obj]
    # Fall back to __dict__ if available; otherwise string repr.
    if hasattr(obj, "__dict__"):
        return _jsonable(vars(obj))
    return str(obj)


def _serialize_drone_state(drone_state: Any) -> Optional[dict[str, Any]]:
    if drone_state is None:
        return None
    if hasattr(drone_state, "__dict__"):
        return _jsonable(vars(drone_state))
    return _jsonable(drone_state)


def _serialize_frame(frame: Any) -> Optional[dict[str, Any]]:
    if frame is None:
        return None
    out: dict[str, Any] = {}
    photo_path = getattr(frame, "photo_path", None)
    if photo_path is not None:
        out["photo_path"] = _jsonable(photo_path)

    dets = getattr(frame, "detection", None)
    if dets is not None:
        det_out = []
        for d in dets:
            det_out.append(
                {
                    "label": d.label,
                    "confidence": d.confidence,
                    "bbox": _jsonable(d.bbox),
                    "track_id": d.track_id,
                    "truth_id": d.truth_id,
                    "time_detected": d.time_ns,
                }
            )
        out["detections"] = det_out
    return out


def log_event(
    event: str,
    *,
    logger: str,
    level: str = "INFO",
    drone_state: Any = None,
    frame: Any = None,
    **fields: Any,
) -> None:
    """
    Append a JSON object line to mission.jsonl.
    Base fields: ts, level, logger, event.
    Payload fields are flexible for backwards compatibility.
    """
    with _lock:
        if _mission_log_path is None:
            return

        # If user forgets to init header, auto-create a minimal one.
        global _initialized_header
        if not _initialized_header:
            try:
                init_mission_log()
            except Exception:
                pass

        record: dict[str, Any] = {
            "ts": _utc_iso(),
            "level": level,
            "logger": logger,
            "event": event,
        }
        ds = _serialize_drone_state(drone_state)
        fr = _serialize_frame(frame)
        if ds is not None:
            record["drone_state"] = ds
        if fr is not None:
            record["frame"] = fr

        for k, v in fields.items():
            if v is None:
                continue
            record[k] = _jsonable(v)

        _append_locked(record)


def _append_locked(obj: dict[str, Any]) -> None:
    assert _mission_log_path is not None
    line = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    with open(_mission_log_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")

