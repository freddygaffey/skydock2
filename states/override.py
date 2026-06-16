from ai_class import Frame

from telemetry import telemetry_singleton
from drone_state import DroneStateForHoming
from states.enum import DroneStateEnum


def override(drone_state:DroneStateForHoming,frame:Frame):
    """Safe/idle state. Halts autonomous motion and gates re-entry into the mission.

    Transitions: RTL if mode==RTL; OVERRIDE while autonomy is disabled or the FC
    is not in GUIDED; HOMING if the pilot force-homing switch is set; otherwise
    SCAN once autonomy is enabled in GUIDED.
    """
    telemetry_singleton.stop_velocity_command()
    if not drone_state.autonomy_enabled:
        telemetry_singleton.stop_velocity_command()
        return DroneStateEnum.OVERRIDE
    elif drone_state.mode == "RTL":
        return DroneStateEnum.RTL
    elif not drone_state.mode == "GUIDED":
        return DroneStateEnum.OVERRIDE
    elif drone_state.force_homing and drone_state.mode == "GUIDED":
        return DroneStateEnum.HOMING
    elif drone_state.autonomy_enabled and drone_state.mode == "GUIDED":
        return DroneStateEnum.SCAN
    else:
        return DroneStateEnum.OVERRIDE

        