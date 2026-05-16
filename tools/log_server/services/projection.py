"""Project detections / image corners to ground coordinates using repo `utils.detection_to_latlon`."""

from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any

from ai_class import Detection
from drone_state import DroneStateForHoming
from utils import detection_to_latlon


_DEFAULT_W = DroneStateForHoming.__dataclass_fields__["width"].default
_DEFAULT_H = DroneStateForHoming.__dataclass_fields__["hight"].default
_PITCH_MM = DroneStateForHoming.SENSOR_PIXEL_PITCH_MM
_FOCAL_MM = DroneStateForHoming.LENS_FOCAL_LENGTH_MM


def drone_state_from_dict(ds: dict | None) -> Any | None:
    """Build a state object compatible with `utils.detection_to_ned` / `detection_to_latlon`.

    Mission JSON stores attitude under ``rotaion`` (nested ``x,y,z`` from the drone dataclass),
    not flat ``rotaion_x``/``_y``/``_z``. Live code also calls ``get_rotation_at_time`` on the
    state object; log replay must supply the same interface.
    """
    if not ds or not isinstance(ds, dict):
        return None
    rot_d = ds.get("rotaion")
    if isinstance(rot_d, dict):
        rx = float(rot_d.get("x") or 0.0)
        ry = float(rot_d.get("y") or 0.0)
        rz = float(rot_d.get("z") or 0.0)
    else:
        rx = float(ds.get("rotaion_x") or 0.0)
        ry = float(ds.get("rotaion_y") or 0.0)
        rz = float(ds.get("rotaion_z") or 0.0)

    class _LogDroneState:
        # `rotaion` must be assignable: `utils.detection_to_ned` sets it from
        # `get_rotation_at_time` each call (matches real DroneStateForHoming).
        __slots__ = (
            "latitude",
            "longitude",
            "altitude_rel_home",
            "rangefinder_m",
            "rotaion",
            "width",
            "hight",
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
            self.hight = int(ds.get("hight") or _DEFAULT_H)
            # utils.detection_to_ned now gates on this; logged states were live at write time.
            self.is_telemetry_ready = True
            self._rx, self._ry, self._rz = rx, ry, rz
            self.rotaion = SimpleNamespace(x=self._rx, y=self._ry, z=self._rz)

        @property
        def fov_x_deg(self) -> float:
            return 2.0 * math.degrees(math.atan(self.width * _PITCH_MM / 2.0 / _FOCAL_MM))

        @property
        def fov_y_deg(self) -> float:
            return 2.0 * math.degrees(math.atan(self.hight * _PITCH_MM / 2.0 / _FOCAL_MM))

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

    Resolution and FOV come from the logged ``drone_state`` (``width``/``hight``
    + lens specs), matching the live geometry in ``utils.detection_to_ned``.
    """
    ds_obj = drone_state_from_dict(ds_dict)
    if ds_obj is None or ds_obj.altitude_rel_home <= 0:
        return None
    w, h = ds_obj.width, ds_obj.hight
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
