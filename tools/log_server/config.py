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
    """Local folder where RPi ``missions/`` logs are synced (``Sync RPi`` / ``pull_logs_rpi.sh``)."""
    root = project_root()
    return Path(os.environ.get("SKYDOCK_RPI_MISSIONS_DIR", str(root / "rpi_missions")))
