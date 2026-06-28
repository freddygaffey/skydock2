"""Locking tests for telemetry/sitl safe fixes (F3, F10, F5).

These exercise Telemetry without opening a serial port by constructing the
instance via __new__ and wiring only the attributes each path touches.

Run with:  python -m pytest tests/test_safe_fixes.py
"""

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import serial

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.support import _StopLoop, heartbeat_msg, ensure_real_module  # noqa: E402

# A sibling test may have stubbed telemetry via sys.modules.setdefault; we need
# the real Telemetry class here (importing it does not open a serial port).
telemetry_mod = ensure_real_module("telemetry")
Telemetry = telemetry_mod.Telemetry


# ---------------------------------------------------------------------------
# F3: mode mapping is complete and unambiguous
# ---------------------------------------------------------------------------

def test_mode_mapping_has_land_and_autorotate():
    assert Telemetry.MODE_MAPPING["LAND"] == 8
    assert Telemetry.MODE_MAPPING["AUTOROTATE"] == 26
    # No duplicate mode numbers (the old dict lost AUTOTUNE=15 to a dup key).
    values = list(Telemetry.MODE_MAPPING.values())
    assert len(values) == len(set(values))
    assert Telemetry.MODE_MAPPING["AUTOTUNE"] == 15


def test_mode_arm_passer_handles_land_without_raising():
    t = Telemetry.__new__(Telemetry)
    t.mode_mapping = dict(Telemetry.MODE_MAPPING)
    t.arm_state = False
    t.current_mode = None

    t.mode_arm_passer(heartbeat_msg(custom_mode=8, armed=True))  # LAND

    assert t.current_mode == "LAND"
    assert t.arm_state is True


# ---------------------------------------------------------------------------
# F10: SerialException on the read loop does not raise NameError
# ---------------------------------------------------------------------------

def test_start_passer_survives_serial_exception(monkeypatch):
    t = Telemetry.__new__(Telemetry)
    t.connection = MagicMock()
    # First read raises (would be NameError pre-fix); second breaks the loop.
    t.connection.recv_msg.side_effect = [serial.SerialException("boom"), _StopLoop()]
    t.drone_state = MagicMock()
    monkeypatch.setattr(telemetry_mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(t, "set_a_message_interval", lambda *a, **k: None)

    with pytest.raises(_StopLoop):
        t.start_passer()

    # The drone_state was never fed a stale/garbage message from the failed read.
    t.drone_state.set_pass_message.assert_not_called()


# ---------------------------------------------------------------------------
# F5: SITL heartbeat probe logs instead of swallowing silently
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# F4: load_mission_file validates the JSON schema with a clear error
# ---------------------------------------------------------------------------

def _write_mission(tmp_path, data):
    import json
    p = tmp_path / "m.json"
    p.write_text(json.dumps(data))
    return str(p)


def test_load_mission_file_missing_keys_raises(tmp_path):
    import sitl
    path = _write_mission(tmp_path, {"weed_locations": []})  # no scan_path
    with pytest.raises(ValueError, match="scan_path"):
        sitl.load_mission_file(path, start_sim_ai=False)


def test_load_mission_file_bad_scan_path_entry_raises(tmp_path):
    import sitl
    path = _write_mission(tmp_path, {"weed_locations": [], "scan_path": [[1.0, 2.0], [3.0]]})
    with pytest.raises(ValueError, match=r"scan_path\[1\]"):
        sitl.load_mission_file(path, start_sim_ai=False)


def test_load_mission_file_valid_loads_waypoints(tmp_path, monkeypatch):
    import sitl
    import DB_abstraction
    from tests.support import FakeDB
    fake = FakeDB()
    fake.backup_and_clear = lambda *a, **k: None
    fake.add_waypoint = lambda wp: fake.waypoints.append(wp)
    monkeypatch.setattr(DB_abstraction, "db_abstraction", fake)

    path = _write_mission(tmp_path, {
        "weed_locations": [{"id": 0, "lat": -35.0, "lon": 149.0}],
        "scan_path": [[-35.0, 149.0], [-35.1, 149.1]],
    })
    data = sitl.load_mission_file(path, start_sim_ai=False)

    assert len(data["scan_path"]) == 2
    assert len(fake.waypoints) == 2
    # Waypoints are built as (lat, lon).
    assert fake.waypoints[0].lat == pytest.approx(-35.0)
    assert fake.waypoints[0].lon == pytest.approx(149.0)


def test_start_sim_reports_when_no_existing_sitl(monkeypatch, capsys):
    import sitl

    def boom(*a, **k):
        raise OSError("no sitl on 14550")

    monkeypatch.setattr(sitl.mavutil, "mavlink_connection", boom)
    monkeypatch.setattr(sitl.subprocess, "Popen", lambda *a, **k: MagicMock())
    monkeypatch.setattr(sitl.time, "sleep", lambda s: None)

    sitl.start_sim(1)

    out = capsys.readouterr().out
    assert "14550" in out  # an informative line was printed, not silent
