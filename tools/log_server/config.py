"""Paths and environment for the log server."""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path

# Repo root (skydock2/) so we can `import utils` (source of truth for projection math).
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _ensure_drone_state_importable() -> None:
    """`utils` imports `drone_state.DroneStateForHoming`; if that module fails to load, stub it."""
    if "drone_state" in sys.modules:
        return
    try:
        import importlib

        importlib.import_module("drone_state")
    except Exception:
        m = types.ModuleType("drone_state")

        class DroneStateForHoming:  # noqa: D401
            """Placeholder so `import utils` succeeds; projection uses attribute-only state objects."""

            pass

        m.DroneStateForHoming = DroneStateForHoming
        sys.modules["drone_state"] = m


_ensure_drone_state_importable()


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def data_paths() -> tuple[Path, Path]:
    root = project_root()
    sim = Path(os.environ.get("SKYDOCK_SIM_DATA_DIR", str(root / "sim_data")))
    missions = Path(os.environ.get("SKYDOCK_MISSIONS_DIR", str(root / "missions")))
    return sim, missions


def rpi_missions_root() -> Path:
    """Local folder where RPi ``missions/`` logs are synced (``Sync RPi`` / tools/sync_rpi_logs.sh)."""
    root = project_root()
    return Path(os.environ.get("SKYDOCK_RPI_MISSIONS_DIR", str(root / "rpi_missions")))


def mavlink_url() -> str | None:
    """pymavlink connection string for live control (e.g. a MAVProxy UDP output:
    ``udpout:127.0.0.1:14550`` or ``udp:0.0.0.0:14551``). Unset → live control disabled."""
    return os.environ.get("SKYDOCK_MAVLINK_URL") or None


def camera_stream_url() -> str | None:
    """URL of the drone's MJPEG/HTTP camera stream (served Pi-side, reached over Wi-Fi /
    reverse-proxy / tunnel). Unset → the GC camera pane shows a 'not configured' note."""
    return os.environ.get("SKYDOCK_CAMERA_STREAM_URL") or None
