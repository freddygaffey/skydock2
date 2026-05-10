import time
from dataclasses import dataclass
from ai_class import Detection

from telemetry import telemetry_singlton
from drone_state import DroneStateForHoming
from states.enum import DroneStateEnum
from ai_callback import Frame


def overide(drone_state:DroneStateForHoming,frame:Frame):
    telemetry_singlton.stop_volocity_command()
    if not drone_state.autonomy_enabled:
        telemetry_singlton.stop_volocity_command()
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

        