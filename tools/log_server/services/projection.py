"""Project detections / image corners to ground coordinates using repo `utils.detection_to_latlon`."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from ai_class import Detection
from drone_state import DroneStateForHoming
from utils import detection_to_latlon


_DEFAULT_W = DroneStateForHoming.__dataclass_fields__["width"].default
_DEFAULT_H = DroneStateForHoming.__dataclass_fields__["height"].default
# Camera FOV is a fixed property of the lens + sensor, independent of the lores buffer
# resolution. Take it straight from drone_state (the single source of truth) — deriving it
# from the 1280px image width understated it ~3x (18.8deg vs the real 55.3x31.2deg).
_FOV_X_DEG = DroneStateForHoming().fov_x_deg
_FOV_Y_DEG = DroneStateForHoming().fov_y_deg


def _first_key(ds: dict, *keys: str) -> Any:
    """Return the first present, non-None value among keys (new name first, legacy fallback)."""
    for k in keys:
        v = ds.get(k)
        if v is not None:
            return v
    return None


def drone_state_from_dict(ds: dict | None) -> Any | None:
    """Build a state object compatible with `utils.detection_to_ned` / `detection_to_latlon`.

    Mission JSON stores attitude under ``rotation`` (nested ``x,y,z`` from the drone
    dataclass), not flat ``rotation_x``/``_y``/``_z``. Logs written before the 2026-06
    typo-rename used ``rotaion``/``hight``; those legacy keys are still accepted so
    historical missions remain replayable. Live code also calls ``get_rotation_at_time``
    on the state object; log replay must supply the same interface.
    """
    if not ds or not isinstance(ds, dict):
        return None
    rot_d = _first_key(ds, "rotation", "rotaion")
    if isinstance(rot_d, dict):
        rx = float(rot_d.get("x") or 0.0)
        ry = float(rot_d.get("y") or 0.0)
        rz = float(rot_d.get("z") or 0.0)
    else:
        rx = float(_first_key(ds, "rotation_x", "rotaion_x") or 0.0)
        ry = float(_first_key(ds, "rotation_y", "rotaion_y") or 0.0)
        rz = float(_first_key(ds, "rotation_z", "rotaion_z") or 0.0)

    class _LogDroneState:
        # `rotation` must be assignable: `utils.detection_to_ned` sets it from
        # `get_rotation_at_time` each call (matches real DroneStateForHoming).
        __slots__ = (
            "latitude",
            "longitude",
            "altitude_rel_home",
            "rangefinder_m",
            "rotation",
            "width",
            "height",
            "is_telemetry_ready",
            "_rx",
            "_ry",
            "_rz",
        )

        def __init__(self) -> None:
            self.latitude = float(ds.get("latitude") or 0.0)
            self.longitude = float(ds.get("longitude") or 0.0)
            self.altitude_rel_home = float(ds.get("altitude_rel_home") or 0.0)
            self.rangefinder_m = float(ds.get("rangefinder_m") or 0.0)
            self.width = int(ds.get("width") or _DEFAULT_W)
            self.height = int(_first_key(ds, "height", "hight") or _DEFAULT_H)
            # utils.detection_to_ned now gates on this; logged states were live at write time.
            self.is_telemetry_ready = True
            self._rx, self._ry, self._rz = rx, ry, rz
            self.rotation = SimpleNamespace(x=self._rx, y=self._ry, z=self._rz)

        @property
        def fov_x_deg(self) -> float:
            return _FOV_X_DEG

        @property
        def fov_y_deg(self) -> float:
            return _FOV_Y_DEG

        def get_rotation_at_time(self, _time_ns: Any) -> Any:
            return SimpleNamespace(x=self._rx, y=self._ry, z=self._rz)

        def get_position_at_time(self, _time_ns: Any) -> Any:
            return SimpleNamespace(lat=self.latitude, lon=self.longitude)

    return _LogDroneState()


def ground_project_one(det: dict, ds: Any) -> dict | None:
    """Project bbox center + four pixel corners to lat/lon via `utils.detection_to_latlon`."""
    bbox = det.get("bbox")
    if not bbox or len(bbox) < 2:
        return None
    try:
        p0, p1 = bbox[0], bbox[1]
        x0, y0 = float(p0[0]), float(p0[1])
        x1, y1 = float(p1[0]), float(p1[1])
    except (TypeError, ValueError, IndexError):
        return None

    label = str(det.get("label") or "?")
    conf = det.get("confidence")
    try:
        full = Detection(
            label=label,
            confidence=float(conf) if conf is not None else 0.0,
            bbox=[(x0, y0), (x1, y1)],
        )
        c_lat, c_lon = detection_to_latlon(ds, full)
        c_lat, c_lon = float(c_lat), float(c_lon)
    except Exception:
        return None

    corners_ll: list[dict[str, float]] = []
    for u, v in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        try:
            pt = Detection(label=label, confidence=0.0, bbox=[(u, v), (u, v)])
            la, lo = detection_to_latlon(ds, pt)
            corners_ll.append({"lat": float(la), "lon": float(lo)})
        except Exception:
            continue

    return {
        "label": label,
        "confidence": conf,
        "bbox_px": bbox,
        "center": {"lat": c_lat, "lon": c_lon},
        "corners": corners_ll,
        "truth_id": det.get("truth_id"),
    }


def camera_fov_footprint_from_drone_dict(ds_dict: dict | None) -> list[dict[str, float]] | None:
    """Project the four image corners to ground using ``utils.detection_to_latlon``.

    Resolution and FOV come from the logged ``drone_state`` (``width``/``height``
    + lens specs), matching the live geometry in ``utils.detection_to_ned``.
    """
    ds_obj = drone_state_from_dict(ds_dict)
    if ds_obj is None or ds_obj.altitude_rel_home <= 0:
        return None
    w, h = ds_obj.width, ds_obj.height
    footprint: list[dict[str, float]] = []
    for u, v in ((0, 0), (w, 0), (w, h), (0, h)):
        try:
            pt = Detection(label="", confidence=0.0, bbox=[(u, v), (u, v)])
            la, lo = detection_to_latlon(ds_obj, pt)
            footprint.append({"lat": float(la), "lon": float(lo)})
        except Exception:
            return None
    return footprint if len(footprint) >= 4 else None


def ground_project_list(
    detections: list[dict], ds: Any | None
) -> tuple[list[dict], str | None]:
    if ds is None:
        return [], "no drone_state on this log line (needed for projection)"
    if ds.altitude_rel_home <= 0:
        return [], "altitude_rel_home must be > 0 to project rays to ground"
    out: list[dict] = []
    for det in detections:
        g = ground_project_one(det, ds)
        if g:
            out.append(g)
    return out, None
