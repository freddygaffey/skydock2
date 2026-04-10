import time

from telemetry import telemetry_singlton
from drone_state import DroneStateForHoming
from ai_class import Frame
from utils import detection_to_latlon, haversine_distance, detection_to_dist, detection_to_ned
from constants import MAX_HOMING_DIST, MIN_ALT, MIN_SPRAY_ERROR, SIM_SPEED
from states.enum import DroneStateEnum
import states.shared_data as shared_data
from DB_abstraction import db_abstraction
from mission_logging import log_event

last_det_time = time.time()

def homing(drone_state:DroneStateForHoming,frame:Frame):
    min_actual = float("inf")
    closest_det = None
    for i in frame.detection:
        dist = detection_to_dist(drone_state,i)
        if dist < min_actual:
            min_actual = dist
            closest_det = i
    if min_actual <= MIN_SPRAY_ERROR:
        if (weed := db_abstraction.get_closest_weed(drone_state)):
            log_event(
                "spray_ready",
                logger="spray",
                level="INFO",
                drone_state=drone_state,
                frame=frame,
                dist_horizontal_m=float(min_actual),
                min_spray_error_m=float(MIN_SPRAY_ERROR),
                target_weed={"id": weed.id, "lat": weed.lat, "lon": weed.lon},
                closest_detection={"time_detected": closest_det.time_ns if closest_det else None},
            )
            db_abstraction.mark_weed_sprayed(weed)
        else: return DroneStateEnum.RTL

        return DroneStateEnum.SPRAY

    global last_det_time
    if closest_det:
        last_det_time = time.time()

    # if (time.time() - shared_data.last_goto_time) > 10 / SIM_SPEED and (time.time() - last_det_time) > 1 / SIM_SPEED:
    #     return DroneStateEnum.GOTO
    
    if closest_det is None:
        telemetry_singlton.send_volocity_command_yaw_stay_same(0, 0, -1)  # ascend to widen FOV
        return DroneStateEnum.HOMING

    # Choose altitude change based on how recently we saw a detection
    if (time.time() - last_det_time) > 1 / SIM_SPEED:
        dalt = 1
    elif drone_state.altitude_rel_home < MIN_ALT:
        dalt = 0
    else:
        dalt = -1

    ned = detection_to_ned(drone_state, closest_det)
    telemetry_singlton.send_displacement_command_yaw_stay_same(ned[0], ned[1], dalt)
    return DroneStateEnum.HOMING
    
    
    
