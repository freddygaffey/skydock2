"""Shared helpers for the flight-stack test suite.

The flight stack binds its collaborators by name at import time
(``from telemetry import telemetry_singleton`` etc.), so tests follow two rules:

1. Stub heavy modules in ``sys.modules`` BEFORE importing the module under test
   (``ensure_stub_module``), or restore the real module if an earlier-collected
   test file installed a stub (``ensure_real_module``).
2. Patch the CONSUMING module's attribute (``states.scan.db_abstraction``),
   never the source module — the consumer holds its own binding.
"""

import importlib
import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock


# MAVLink constants used by fake messages (values from pymavlink common.xml).
MAV_MODE_FLAG_SAFETY_ARMED = 128
MAV_TYPE_QUADROTOR = 2
MAV_TYPE_GCS = 6


class _StopLoop(Exception):
    """Raised from a mocked call to break out of an infinite loop under test."""


def ensure_stub_module(name: str, **attrs) -> types.ModuleType:
    """Install (or reuse) a stub module so importing `name` has no side effects."""
    mod = sys.modules.get(name)
    if mod is None:
        mod = types.ModuleType(name)
        sys.modules[name] = mod
    for k, v in attrs.items():
        if not hasattr(mod, k):
            setattr(mod, k, v)
    return mod


def ensure_real_module(name: str) -> types.ModuleType:
    """Import the real `name`, evicting a stub left in sys.modules by another test file.

    Stubs created via types.ModuleType have no __file__/__spec__; real modules do.
    Already-imported consumers keep their old bindings (by design — patch their
    attributes instead).
    """
    mod = sys.modules.get(name)
    if mod is not None and getattr(mod, "__file__", None) is None:
        del sys.modules[name]
    return importlib.import_module(name)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeTelemetry:
    """Records the commands a state function would send to the flight controller."""

    def __init__(self, drone_state=None):
        self.drone_state = drone_state
        self.fly_to_calls: list[tuple] = []          # (lat, lon, alt)
        self.velocity_calls: list[tuple] = []        # (mx, my, mz)
        self.displacement_calls: list[tuple] = []    # (mx, my, mz)
        self.stop_calls: int = 0
        self.modes_set: list[str] = []

    def fly_to_point(self, lat, lon, alt_above_home, bitmask=3576, speed_ms=None):
        self.fly_to_calls.append((lat, lon, alt_above_home))

    def send_velocity_command_yaw_stay_same(self, mx=0.0, my=0.0, mz=0.0, bitmask=None):
        self.velocity_calls.append((mx, my, mz))

    def send_displacement_command_yaw_stay_same(self, mx, my, mz, bitmask=4088):
        self.displacement_calls.append((mx, my, mz))

    def stop_velocity_command(self):
        self.stop_calls += 1

    def set_mode(self, mode):
        self.modes_set.append(mode)

    def get_mode(self):
        return self.modes_set[-1] if self.modes_set else None


class FakeDB:
    """In-memory stand-in for DB_abstraction.DBAbstraction (same method names)."""

    def __init__(self):
        self.waypoints: list = []       # objects with .lat/.lon/.id, served in order
        self.weeds: list = []           # objects with .lat/.lon/.id
        self.snapshots: list = []
        self.logged_states: list[tuple] = []
        self.logged_weeds: list = []
        self.traveled_waypoints: list = []
        self.traveled_weeds: list = []
        self.sprayed_weeds: list = []
        self.closest_weed = None        # value returned by get_closest_weed

    def get_next_waypoint(self):
        return self.waypoints[0] if self.waypoints else None

    def mark_waypoint_traveled(self, waypoint):
        self.traveled_waypoints.append(waypoint)
        if waypoint in self.waypoints:
            self.waypoints.remove(waypoint)

    def log_drone_state_and_frame(self, drone_state, frame):
        self.logged_states.append((drone_state, frame))
        return len(self.logged_states)

    def get_all_snapshots(self):
        return self.snapshots

    def get_closest_weed(self, drone_state, only_unsprayed=True, skip_traveled=True):
        return self.closest_weed

    def mark_weed_traveled(self, weed):
        self.traveled_weeds.append(weed)

    def mark_weed_sprayed(self, weed):
        self.sprayed_weeds.append(weed)

    def log_weed(self, weed):
        self.logged_weeds.append(weed)
        return len(self.logged_weeds)


# ---------------------------------------------------------------------------
# Fake MAVLink messages (duck-typed; only the fields the code reads)
# ---------------------------------------------------------------------------

def heartbeat_msg(custom_mode=4, armed=True, from_gcs=False):
    """HEARTBEAT: custom_mode 4 = GUIDED, 6 = RTL, 8 = LAND (ArduCopter)."""
    return SimpleNamespace(
        _type="HEARTBEAT",
        custom_mode=custom_mode,
        base_mode=MAV_MODE_FLAG_SAFETY_ARMED if armed else 0,
        type=MAV_TYPE_GCS if from_gcs else MAV_TYPE_QUADROTOR,
    )


def global_position_msg(lat=-35.363261, lon=149.165230, alt_m=10.0,
                        vx_ms=0.0, vy_ms=0.0, vz_ms=0.0,
                        hdg_deg=0.0, time_boot_ms=1000):
    """GLOBAL_POSITION_INT in raw wire units (degE7, mm, cm/s, cdeg)."""
    return SimpleNamespace(
        _type="GLOBAL_POSITION_INT",
        time_boot_ms=time_boot_ms,
        lat=int(lat * 1e7),
        lon=int(lon * 1e7),
        relative_alt=int(alt_m * 1000),
        vx=int(vx_ms * 100),
        vy=int(vy_ms * 100),
        vz=int(vz_ms * 100),
        hdg=65535 if hdg_deg is None else int(hdg_deg * 100),
    )


def attitude_msg(roll=0.0, pitch=0.0, yaw=0.0,
                 rollspeed=0.0, pitchspeed=0.0, yawspeed=0.0):
    return SimpleNamespace(
        _type="ATTITUDE",
        roll=roll, pitch=pitch, yaw=yaw,
        rollspeed=rollspeed, pitchspeed=pitchspeed, yawspeed=yawspeed,
    )


def rc_channels_msg(chan16_raw=900):
    return SimpleNamespace(_type="RC_CHANNELS", chan16_raw=chan16_raw)


def distance_sensor_msg(distance_cm=500):
    return SimpleNamespace(_type="DISTANCE_SENSOR", current_distance=distance_cm)
