"""SITL integration smoke tests: real ArduPilot SITL + real Telemetry stack.

Covers the layers the fast unit suite can only fake:
- MAVLink stream populates DroneStateForHoming (telemetry ready)
- the measured sim_speed estimator converges against a real 10x SITL
- force-arm + takeoff works end to end
- GUIDED velocity commands actually move the vehicle (what homing relies on)

Run with:  python3 -m pytest tests_sitl/ -q
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests_sitl.conftest import SITL_SPEEDUP, wait_for  # noqa: E402
from constants import TARGET_SIM_SPEED  # noqa: E402
import sitl as sitl_mod  # noqa: E402


def test_telemetry_becomes_ready(telemetry):
    assert wait_for(lambda: telemetry.drone_state.is_telemetry_ready, 30), \
        "no ATTITUDE received from SITL within 30s"
    assert wait_for(lambda: telemetry.drone_state.latitude != 0, 30), \
        "no GLOBAL_POSITION_INT received from SITL within 30s"


def test_sim_speed_estimator_converges(telemetry):
    # Test process runs without --speedup, so the seed is TARGET_SIM_SPEED (1);
    # SITL runs at SITL_SPEEDUP (10). The SYSTEM_TIME-driven estimator must
    # move well away from the seed toward the real ratio. Loose lower bound:
    # the achieved speedup depends on machine load.
    assert TARGET_SIM_SPEED == 1
    assert wait_for(lambda: telemetry.drone_state.sim_speed > 3, 60), (
        f"sim_speed stayed at {telemetry.drone_state.sim_speed:.2f}; "
        f"expected to move toward ~{SITL_SPEEDUP}"
    )


def test_arm_and_takeoff(telemetry):
    assert sitl_mod.arm_and_takeoff(
        telemetry.connection, telemetry, altitude=8, speed=SITL_SPEEDUP
    ), "SITL failed to arm/takeoff"
    # arm_and_takeoff returns once alt > 0.5; require a real sustained climb
    # so a noise blip can't fake a takeoff.
    assert wait_for(lambda: telemetry.drone_state.altitude_rel_home > 4, 30), (
        f"takeoff did not climb: alt={telemetry.drone_state.altitude_rel_home:.2f}m, "
        f"armed={telemetry.arm_state}, mode={telemetry.drone_state.mode}"
    )


def test_velocity_command_moves_drone(telemetry):
    # Ensure airborne (idempotent if the previous test already took off).
    assert sitl_mod.arm_and_takeoff(
        telemetry.connection, telemetry, altitude=8, speed=SITL_SPEEDUP
    )
    assert wait_for(lambda: telemetry.drone_state.altitude_rel_home > 4, 30), (
        f"not at altitude for velocity test: "
        f"alt={telemetry.drone_state.altitude_rel_home:.2f}m, "
        f"armed={telemetry.arm_state}, mode={telemetry.drone_state.mode}"
    )

    lat0 = telemetry.drone_state.latitude
    # Fly north at 1 m/s; setpoints must be re-sent, so stream them for ~2s of
    # wall time (~20 sim-seconds at 10x => ~20 m => ~1.8e-4 deg latitude).
    end = time.time() + 2.0
    while time.time() < end:
        telemetry.send_velocity_command_yaw_stay_same(mx=1.0, my=0.0, mz=0.0)
        time.sleep(0.1)
    telemetry.send_velocity_command_yaw_stay_same(mx=0.0, my=0.0, mz=0.0)

    assert wait_for(lambda: telemetry.drone_state.latitude - lat0 > 3e-5, 15), (
        f"latitude moved {telemetry.drone_state.latitude - lat0:.2e} deg; "
        "expected clear northward motion"
    )
