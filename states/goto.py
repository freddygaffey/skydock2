import time
from dataclasses import dataclass
from ai_class import Detection

from telemetry import telemetry_singlton
from drone_state import DroneStateForHoming
from ai_class import Frame
from DB_abstraction import db_abstraction, Weed
from utils import detection_to_latlon, haversine_distance, detection_to_ned
from constants import GOTO_ALT, MAX_HOMING_DIST
from states.enum import DroneStateEnum
import states.shared_data as shared_data


def goto(drone_state:DroneStateForHoming,frame:Frame):
    shared_data.last_goto_time = time.time()
    weed = db_abstraction.get_closest_weed(drone_state)
    if not weed:
        print("[GOTO] no unsprayed weed -> RTL")
        return DroneStateEnum.RTL
    dist = haversine_distance(weed.lat,weed.lon,drone_state.latitude,drone_state.longitude)
    print(f"[GOTO] weed id={weed.id} lat={weed.lat:.6f} lon={weed.lon:.6f} dist={dist:.2f}m alt={drone_state.altitude_rel_home:.2f}")
    if dist < MAX_HOMING_DIST:
        # if drone_state.altitude_rel_home > GOTO_ALT + 1:
        #     telemetry_singlton.fly_to_point(weed.lat,weed.lon,GOTO_ALT)
        #     return DroneStateEnum.GOTO
        print(f"[GOTO] within MAX_HOMING_DIST={MAX_HOMING_DIST} -> mark traveled, HOMING")
        db_abstraction.mark_weed_traveled(weed)
        return DroneStateEnum.HOMING
    print(f"[GOTO] flying to weed id={weed.id} alt={GOTO_ALT}")
    telemetry_singlton.fly_to_point(weed.lat,weed.lon,GOTO_ALT)
    return DroneStateEnum.GOTO
