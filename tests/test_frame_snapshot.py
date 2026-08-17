"""Regression tests for the latency-staleness fix.

A Frame must carry a frozen snapshot of the drone state at capture time:
- scalars (position/attitude) must NOT move when the live state updates later
- the snapshot's history deques must be detached from the live (thread-mutated)
  ones, while keeping is_telemetry_ready True and the time-lookup methods sane
- taking snapshots while another thread mutates the live state must never
  raise (the deepcopy version died on "deque mutated during iteration")
- scan() must log the frame's capture state, not the live navigation state

Run with:  python -m pytest tests/test_frame_snapshot.py
"""

import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_class import Detection, Frame  # noqa: E402
from drone_state import DroneStateForHoming, GPSFix, Rotation  # noqa: E402


def live_state(lat=-35.363261, lon=149.165230, alt=10.0, yaw=0.5):
    s = DroneStateForHoming()
    s.latitude, s.longitude, s.altitude_rel_home = lat, lon, alt
    rot = Rotation(time_ns=1000, x=0.1, y=0.2, z=yaw)
    s.rotation = rot
    s.rotation_history.append(rot)
    s.gps_history.append(GPSFix(time_ns=1000, lat=lat, lon=lon, vx=1.0, vy=0.0))
    return s


def test_snapshot_scalars_freeze_at_capture():
    s = live_state(lat=-35.0)
    snap = s.snapshot()
    s.latitude = -36.0                     # telemetry moves on
    s.rotation = Rotation(2000, 0.9, 0.9, 0.9)
    assert snap.latitude == -35.0
    assert snap.rotation.z == 0.5


def test_snapshot_histories_are_detached():
    s = live_state()
    snap = s.snapshot()
    # live histories keep growing; the snapshot must not see it
    s.gps_history.append(GPSFix(time_ns=9999, lat=-36.0, lon=150.0, vx=5, vy=5))
    s.rotation_history.append(Rotation(9999, 1.5, 1.5, 1.5))

    assert snap.is_telemetry_ready
    # rotation lookups return the capture attitude for any timestamp
    assert snap.get_rotation_at_time(123456).z == 0.5
    # empty gps_history falls back to the frozen scalars, not the live fix
    fix = snap.get_position_at_time(123456)
    assert fix.lat == snap.latitude
    assert fix.lon == snap.longitude


def test_frame_snapshots_state_not_references_it():
    s = live_state(lat=-35.0)
    frame = Frame([], drone_state=s)
    assert frame.drone_state is not s
    s.latitude = -36.0
    assert frame.drone_state.latitude == -35.0


def test_snapshot_survives_concurrent_history_mutation():
    # Regression: deepcopy iterated the live deques while the telemetry thread
    # appended -> RuntimeError -> sim_ai thread died silently.
    s = live_state()
    stop = threading.Event()

    def mutate():
        i = 0
        while not stop.is_set():
            i += 1
            s.rotation_history.append(Rotation(i, 0, 0, 0))
            s.gps_history.append(GPSFix(i, -35.0, 149.0, 0, 0))

    t = threading.Thread(target=mutate, daemon=True)
    t.start()
    try:
        deadline = time.time() + 0.5
        while time.time() < deadline:
            snap = s.snapshot()           # must never raise
            assert snap.is_telemetry_ready
    finally:
        stop.set()
        t.join(timeout=2)


def test_scan_logs_capture_state_not_live_state(monkeypatch):
    # The DB snapshot must pair detections with the state that captured them;
    # navigation uses the live state, logging uses frame.drone_state.
    import states.scan as scan_mod

    capture = live_state(lat=-35.0001)
    live = live_state(lat=-35.0002)       # drone has moved since capture
    frame = Frame([], drone_state=capture)

    logged = {}
    db = SimpleNamespace(
        get_next_waypoint=lambda: SimpleNamespace(lat=-35.0, lon=149.0, id=1),
        log_drone_state_and_frame=lambda ds, fr: logged.update(state=ds, frame=fr),
        mark_waypoint_traveled=lambda wp: None,
    )
    monkeypatch.setattr(scan_mod, "db_abstraction", db)
    monkeypatch.setattr(scan_mod, "telemetry_singleton", MagicMock())

    scan_mod.scan(live, frame)

    assert logged["state"].latitude == frame.drone_state.latitude
    assert logged["state"].latitude != live.latitude
