"""SITL integration test fixtures.

Boots a headless ArduPilot SITL (or reuses one already on udp:14550), then
provides a real Telemetry connected to it. Skips cleanly when the ArduPilot
checkout / venv are missing so `pytest tests_sitl/` is safe on any machine.

Run with:  python3 -m pytest tests_sitl/ -q
(NOT part of the fast core suite in tests/ — this one takes ~1-2 minutes.)
"""

import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SITL_UDP = "udp:127.0.0.1:14550"
SITL_SPEEDUP = 10
ARDUPILOT_DIR = Path(os.environ.get("ARDUPILOT_DIR", Path.home() / "ardupilot"))
VENV_ACTIVATE = Path(os.environ.get("ARDUPILOT_VENV", Path.home() / "venv-ardupilot")) / "bin" / "activate"


def _unavailable(reason: str):
    """Missing SITL skips locally but must FAIL in CI (REQUIRE_SITL=1), so a
    broken runner setup can't silently pass as all-skipped."""
    if os.environ.get("REQUIRE_SITL"):
        pytest.fail(reason)
    pytest.skip(reason)

LAUNCH_CMD = (
    f"source {VENV_ACTIVATE} && "
    f"cd {ARDUPILOT_DIR}/ArduCopter && "
    f"python {ARDUPILOT_DIR}/Tools/autotest/sim_vehicle.py "
    f"-v Copter -N --speedup {SITL_SPEEDUP} "
    f"--location CMAC --auto-offset-line 90,10 -m --daemon"
)


def _log_tail(log_path, max_chars: int = 3000) -> str:
    try:
        return Path(log_path).read_text(errors="replace")[-max_chars:]
    except OSError:
        return "<no log>"


def _heartbeat_on_14550(timeout_s: float) -> bool:
    from pymavlink import mavutil
    try:
        conn = mavutil.mavlink_connection(SITL_UDP, timeout=2)
        msg = conn.wait_heartbeat(timeout=timeout_s)
        conn.close()
        return msg is not None
    except Exception:
        return False


@pytest.fixture(scope="session")
def sitl():
    """A running SITL on udp:14550 — reused if already up, else launched headless."""
    if _heartbeat_on_14550(3):
        yield "reused"
        return  # leave an externally started SITL alone

    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("127.0.0.1", 14550))
        s.close()
    except OSError:
        _unavailable("udp:14550 is bound by another process (a live sim session?); "
                     "not launching a competing SITL")

    if not (ARDUPILOT_DIR / "ArduCopter").is_dir() or not VENV_ACTIVATE.exists():
        _unavailable("ArduPilot checkout or venv-ardupilot missing; cannot launch SITL")

    log_path = Path(tempfile.mkdtemp(prefix="sitl_test_")) / "sitl.log"
    with open(log_path, "w") as log:
        proc = subprocess.Popen(
            ["bash", "-c", LAUNCH_CMD],
            stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True,  # own process group so teardown can kill children
        )

    deadline = time.time() + 90
    while time.time() < deadline:
        if _heartbeat_on_14550(3):
            break
        if proc.poll() is not None:
            _unavailable(f"SITL exited during boot; log tail:\n{_log_tail(log_path)}")
        time.sleep(1)
    else:
        os.killpg(proc.pid, signal.SIGKILL)
        _unavailable(f"SITL never produced a heartbeat; log tail:\n{_log_tail(log_path)}")

    yield proc

    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    # sim_vehicle re-parents children on some platforms; make sure nothing lingers.
    subprocess.run(["pkill", "-f", "bin/arducopter"], check=False)
    subprocess.run(["pkill", "-f", "mavproxy"], check=False)


@pytest.fixture(scope="session")
def telemetry(sitl):
    """A real Telemetry connected to SITL, with mission logging pointed at a temp dir.

    Telemetry's passer thread is non-daemon and never exits; patch Thread so the
    pytest process can still terminate.
    """
    import mission_logging
    mission_dir = Path(tempfile.mkdtemp(prefix="sitl_test_mission_"))
    mission_logging.configure_mission_dir(mission_dir)
    mission_logging.init_mission_log(is_sim=True)

    import telemetry as telemetry_mod

    class _DaemonThread(threading.Thread):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.daemon = True

    original_thread = telemetry_mod.threading.Thread
    telemetry_mod.threading.Thread = _DaemonThread
    try:
        tel = telemetry_mod.Telemetry(SITL_UDP)
    finally:
        telemetry_mod.threading.Thread = original_thread

    yield tel


def wait_for(predicate, timeout_s: float, interval_s: float = 0.2):
    """Poll predicate until true or timeout; returns the final result."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval_s)
    return predicate()
