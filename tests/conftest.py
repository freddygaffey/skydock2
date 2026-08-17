"""Shared fixtures for the flight-stack test suite.

Intentionally does NOT import telemetry / fsm / states.* / DB_abstraction /
mission_logging at module scope: individual test files decide whether those are
stubbed or real (see tests/support.py), and importing them here would freeze
that choice for the whole session.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Collection-time guard: DB_abstraction instantiates DBAbstraction() at import,
# which creates an engine at DB._db_path (default "droneDB.db" in the CWD).
# Point the default at a throwaway temp dir so no test run can ever write a
# stray droneDB.db into the repo.
import DB  # noqa: E402  (only sqlalchemy models; import has no side effects)

_GUARD_DIR = tempfile.mkdtemp(prefix="skydock_tests_")
DB.set_db_path(os.path.join(_GUARD_DIR, "import_default.db"))

HOME_LAT = -35.363261
HOME_LON = 149.165230


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

@pytest.fixture
def make_drone_state():
    """Factory for a telemetry-ready DroneStateForHoming (same shape as the
    make_state helper in test_geometry_math.py)."""
    from drone_state import DroneStateForHoming, Rotation, GPSFix

    def _make(lat=HOME_LAT, lon=HOME_LON, alt=10.0,
              roll=0.0, pitch=0.0, yaw=0.0,
              mode="GUIDED", autonomy_enabled=True, force_homing=False,
              rangefinder_m=0.0, heading=0.0,
              vx=0.0, vy=0.0, ready=True):
        s = DroneStateForHoming()
        s.latitude = lat
        s.longitude = lon
        s.altitude_rel_home = alt
        s.mode = mode
        s.autonomy_enabled = autonomy_enabled
        s.force_homing = force_homing
        s.rangefinder_m = rangefinder_m
        s.heading = heading
        s.velocity_x = vx
        s.velocity_y = vy
        if ready:
            rot = Rotation(time_ns=0, x=roll, y=pitch, z=yaw)
            s.rotation = rot
            s.rotation_history.append(rot)  # makes is_telemetry_ready True
            s.gps_history.append(GPSFix(time_ns=0, lat=lat, lon=lon, vx=vx, vy=vy))
        return s

    return _make


@pytest.fixture
def make_detection():
    """Factory for a Detection at pixel (px, py); defaults to image centre."""
    from ai_class import Detection

    def _make(px=640.0, py=640.0, half=5.0, label="sports ball",
              confidence=0.9, time_ns=0, truth_id=None):
        return Detection(label=label, confidence=confidence,
                         bbox=[(px - half, py - half), (px + half, py + half)],
                         truth_id=truth_id, time_ns=time_ns)

    return _make


@pytest.fixture
def make_frame():
    """Factory for a Frame holding the given detections."""
    from ai_class import Frame

    def _make(*detections, drone_state=None, photo_path="No photo taken"):
        # Frames with detections must carry a drone_state (fail-fast invariant
        # in Frame.__init__); default one in for tests that don't care.
        if detections and drone_state is None:
            from drone_state import DroneStateForHoming
            drone_state = DroneStateForHoming()
        return Frame(list(detections), photo_path=photo_path, drone_state=drone_state)

    return _make


@pytest.fixture
def fake_telemetry():
    from tests.support import FakeTelemetry
    return FakeTelemetry()


@pytest.fixture
def fake_db():
    from tests.support import FakeDB
    return FakeDB()


# ---------------------------------------------------------------------------
# Real-DB fixture (temp SQLite per test)
# ---------------------------------------------------------------------------

@pytest.fixture
def fresh_db(tmp_path):
    """A real DBAbstraction backed by a fresh SQLite file in tmp_path.

    DatabaseSession caches its engine as class attributes, so the singleton is
    reset around each use.
    """
    from tests.support import ensure_real_module
    DB_mod = ensure_real_module("DB")
    dba_mod = ensure_real_module("DB_abstraction")

    old_engine = DB_mod.DatabaseSession._engine
    DB_mod.set_db_path(str(tmp_path / "test.db"))
    DB_mod.DatabaseSession._instance = None
    dba = dba_mod.DBAbstraction()
    try:
        yield dba
    finally:
        engine = DB_mod.DatabaseSession._engine
        if engine is not None and engine is not old_engine:
            engine.dispose()
        DB_mod.DatabaseSession._instance = None
        DB_mod.set_db_path(os.path.join(_GUARD_DIR, "import_default.db"))


# ---------------------------------------------------------------------------
# Global-state hygiene
# ---------------------------------------------------------------------------

def _reset_flight_globals():
    """Reset module-level mutable state, tolerating stubbed/absent modules."""
    homing = sys.modules.get("states.homing")
    if homing is not None:
        if hasattr(homing, "_last_alt_warn"):
            homing._last_alt_warn = {}
    scan = sys.modules.get("states.scan")
    if scan is not None and hasattr(scan, "_scan_data_processed"):
        scan._scan_data_processed = False
    shared = sys.modules.get("states.shared_data")
    if shared is not None:
        if hasattr(shared, "last_goto_time"):
            shared.last_goto_time = 0.0
        if hasattr(shared, "last_det_time"):
            shared.last_det_time = None
        if hasattr(shared, "start_homing_time"):
            shared.start_homing_time = None
        for pid_name in ("N_pid", "E_pid"):
            pid = getattr(shared, pid_name, None)
            if pid is not None:
                pid.clear_history()
    ai = sys.modules.get("ai_class")
    if ai is not None and getattr(ai, "ai_storage_singleton", None) is not None:
        ai.ai_storage_singleton.is_ai_running = False
        ai.ai_storage_singleton.current_frame = ai.Frame([])


@pytest.fixture
def reset_state_globals():
    """Clean module-level FSM/AI state before and after a test."""
    _reset_flight_globals()
    yield
    _reset_flight_globals()


@pytest.fixture
def constants_guard():
    """Snapshot and restore all UPPERCASE constants around a test."""
    import constants
    saved = {k: v for k, v in vars(constants).items() if k.isupper()}
    yield constants
    for k, v in saved.items():
        setattr(constants, k, v)
