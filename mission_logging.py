"""
Structured mission logging — the single source of truth for ``missions/NNNN/mission.jsonl``.

Design (schema v2):
- Call sites pass RAW project objects (DroneStateForHoming, Frame, Detection, DroneStateEnum,
  Rotation, ...). All formatting lives here, so producers stay terse and the on-disk schema is
  defined in exactly one place.
- Every record carries a canonical envelope injected centrally: ``time_ns`` (int, the machine
  key), ``ts`` (ISO string, human-readable), ``level``, ``logger``, ``event``.
- Encoding is explicit and type-aware (never reflective ``vars()``), so renaming an internal
  field can't silently reshape the log. Enums encode to ``.name`` ("SCAN"), never ``str(enum)``.
- ``EVENTS`` is the authoritative event registry; unregistered names warn (but still log).
- ``iter_events`` is the one reader every tool should import; it surfaces malformed lines on
  stderr instead of silently dropping them.

Clean break from v1: legacy logs are NOT normalized by the reader.
"""

import enum as _enum
import dataclasses as _dataclasses
import fcntl
import json
import os
import sys
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

SCHEMA_VERSION = 2

_lock = threading.RLock()
_mission_dir: Optional[Path] = None
_mission_log_path: Optional[Path] = None
_initialized_header: bool = False


# ── Event registry ────────────────────────────────────────────────────────────
# Every event a producer may emit. Keep in sync with call sites; the contract test
# (tests/test_log_contract.py) asserts producers and consumers stay within this set.
EVENTS: frozenset[str] = frozenset({
    # main.py
    "mission_start", "constants_snapshot", "mission_plan",
    # fsm.py
    "fsm_transition", "fsm_tick",
    # telemetry.py
    "telemetry_sample", "move_command",
    # sim_ai.py
    "sim_vision_params",
    # states/scan.py
    "weed_detected",
    # states/spray.py + states/homing.py
    "spray_attempt", "spray_miss", "spray_ready",
    "homing_give_up_timeout", "homing_give_up_no_det", "homing_alt_cap", "homing_tick",
    # DB_abstraction.py
    "db_waypoint_add", "db_waypoint_traveled", "db_weed_add", "db_weed_traveled",
    "db_weed_sprayed", "db_snapshot", "db_backup", "db_clear_all",
})

_VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_LEVEL_ALIASES = {"WARN": "WARNING", "ERR": "ERROR", "FATAL": "CRITICAL"}

_warned_unknown_types: set[str] = set()
_warned_unknown_events: set[str] = set()


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _now_ns() -> int:
    import time
    return time.time_ns()


def _norm_level(level: Any) -> str:
    s = str(level).upper()
    s = _LEVEL_ALIASES.get(s, s)
    return s if s in _VALID_LEVELS else "INFO"


# ── Encoders (explicit, type-aware, no project imports — dispatch by class name) ──

def _encode(v: Any) -> Any:
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, _enum.Enum):
        return v.name
    if isinstance(v, Path):
        return str(v)
    if isinstance(v, dict):
        return {str(k): _encode(x) for k, x in v.items() if x is not None}
    if isinstance(v, (list, tuple, set, deque)):
        return [_encode(x) for x in v]

    cls = type(v).__name__
    if cls == "DroneStateForHoming":
        return _encode_drone_state(v)
    if cls == "Frame":
        return _encode_frame(v)
    if cls == "Detection":
        return _encode_detection(v)
    if cls == "Rotation":
        return _encode_rotation(v)
    if cls == "GPSFix":
        return _encode_gpsfix(v)
    if _dataclasses.is_dataclass(v):
        # Declared fields only — still explicit, just not hand-listed.
        return {f.name: _encode(getattr(v, f.name)) for f in _dataclasses.fields(v)}

    # Unknown object: surface it once instead of silently reflecting __dict__.
    if cls not in _warned_unknown_types:
        _warned_unknown_types.add(cls)
        print(f"[mission_logging] WARNING: no encoder for type {cls!r}; logging str()",
              file=sys.stderr)
    return str(v)


def _encode_rotation(rot: Any) -> Optional[dict[str, Any]]:
    if rot is None:
        return None
    return {
        "time_ns": getattr(rot, "time_ns", None),
        "x": getattr(rot, "x", None),
        "y": getattr(rot, "y", None),
        "z": getattr(rot, "z", None),
        "dx": getattr(rot, "dx", None),
        "dy": getattr(rot, "dy", None),
        "dz": getattr(rot, "dz", None),
    }


def _encode_gpsfix(fix: Any) -> Optional[dict[str, Any]]:
    if fix is None:
        return None
    return {
        "time_ns": getattr(fix, "time_ns", None),
        "lat": getattr(fix, "lat", None),
        "lon": getattr(fix, "lon", None),
        "vx": getattr(fix, "vx", None),
        "vy": getattr(fix, "vy", None),
    }


def _encode_drone_state(ds: Any) -> Optional[dict[str, Any]]:
    if ds is None:
        return None
    return {
        "latitude": getattr(ds, "latitude", None),
        "longitude": getattr(ds, "longitude", None),
        "altitude_rel_home": getattr(ds, "altitude_rel_home", None),
        "velocity_x": getattr(ds, "velocity_x", None),
        "velocity_y": getattr(ds, "velocity_y", None),
        "velocity_z": getattr(ds, "velocity_z", None),
        "heading": getattr(ds, "heading", None),
        "mode": getattr(ds, "mode", None),
        "arm_state": getattr(ds, "arm_state", None),  # set dynamically on HEARTBEAT; may be absent
        "autonomy_enabled": getattr(ds, "autonomy_enabled", None),
        "force_homing": getattr(ds, "force_homing", None),
        "rangefinder_m": getattr(ds, "rangefinder_m", None),
        "width": getattr(ds, "width", None),
        "hight": getattr(ds, "hight", None),
        # NB: corrected spelling on disk. Source field is the dataclass's `rotaion`.
        "rotation": _encode_rotation(getattr(ds, "rotaion", None)),
        "rotation_history": [_encode_rotation(r) for r in getattr(ds, "rotaion_history", []) or []],
        "gps_history": [_encode_gpsfix(g) for g in getattr(ds, "gps_history", []) or []],
    }


def _encode_detection(d: Any) -> dict[str, Any]:
    return {
        "label": getattr(d, "label", None),
        "confidence": getattr(d, "confidence", None),
        "bbox": _encode(getattr(d, "bbox", None)),
        "track_id": getattr(d, "track_id", None),
        "truth_id": getattr(d, "truth_id", None),
        "time_detected": getattr(d, "time_ns", None),
    }


def _encode_frame(frame: Any) -> Optional[dict[str, Any]]:
    if frame is None:
        return None
    out: dict[str, Any] = {}
    photo_path = getattr(frame, "photo_path", None)
    if photo_path is not None:
        out["photo_path"] = _encode(photo_path)
    width = getattr(frame, "width", None)
    hight = getattr(frame, "hight", None)
    if width is not None:
        out["width"] = width
    if hight is not None:
        out["hight"] = hight
    dets = getattr(frame, "detection", None)
    if dets is not None:
        out["detections"] = [_encode_detection(d) for d in dets]
    return out


# ── Mission directory allocation / configuration ──────────────────────────────

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

    lock_path = missions_root / ".allocate.lock"
    lock_fd = open(lock_path, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

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

        counter_path.write_text(str(next_id + 1), encoding="utf-8")
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()

    return mission_dir


def configure_mission_dir(mission_dir: Path) -> None:
    global _mission_dir, _mission_log_path, _initialized_header
    with _lock:
        _mission_dir = Path(mission_dir)
        _mission_log_path = _mission_dir / "mission.jsonl"
        _initialized_header = False


def init_mission_log(
    *,
    schema_version: int = SCHEMA_VERSION,
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
            "time_ns": _now_ns(),
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


# ── Writing ───────────────────────────────────────────────────────────────────

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
    Append one JSON record to mission.jsonl.

    The envelope (time_ns, ts, level, logger, event) is built here. ``drone_state`` and
    ``frame`` are encoded with their dedicated explicit encoders; every other keyword value
    is run through the generic encoder, so call sites may pass raw project objects (e.g.
    ``state_to=DroneStateEnum.SCAN`` → ``"SCAN"``) without formatting them by hand.
    """
    with _lock:
        if _mission_log_path is None:
            return

        global _initialized_header
        if not _initialized_header:
            try:
                init_mission_log()
            except Exception:
                pass

        if event not in EVENTS and event not in _warned_unknown_events:
            _warned_unknown_events.add(event)
            print(f"[mission_logging] WARNING: unregistered event {event!r}; "
                  f"add it to EVENTS in mission_logging.py", file=sys.stderr)

        record: dict[str, Any] = {
            "time_ns": _now_ns(),
            "ts": _utc_iso(),
            "level": _norm_level(level),
            "logger": logger,
            "event": event,
        }
        if drone_state is not None:
            record["drone_state"] = _encode_drone_state(drone_state)
        if frame is not None:
            record["frame"] = _encode_frame(frame)

        for k, v in fields.items():
            if v is None:
                continue
            record[k] = _encode(v)

        _append_locked(record)


def _append_locked(obj: dict[str, Any]) -> None:
    assert _mission_log_path is not None
    line = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    with open(_mission_log_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ── Reading (the one authoritative parser tools should import) ────────────────

def iter_events(path: Any, *, strict: bool = False) -> Iterator[dict[str, Any]]:
    """
    Yield event records from a mission.jsonl file.

    Unlike the old per-tool parsers, malformed lines are NOT silently dropped: by default a
    warning naming the file and line number is written to stderr (so corruption is visible);
    with ``strict=True`` a JSONDecodeError is raised instead.
    """
    path = Path(path)
    with open(path, "r", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                yield json.loads(raw)
            except json.JSONDecodeError as e:
                if strict:
                    raise
                print(f"[mission_logging] WARNING: skipping malformed line "
                      f"{path}:{lineno}: {e}", file=sys.stderr)
                continue
