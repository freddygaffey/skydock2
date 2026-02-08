import time

from telemetry import telemetry_singlton
from drone_state import DroneStateForHoming
from ai_class import Frame
from utils import detection_to_latlon, haversine_distance, detection_to_dist, detection_to_ned
from states.constants import MAX_HOMING_DIST, MIN_ALT, MIN_SPRAY_ERROR
from states.enum import DroneStateEnum
from DB_abstraction import db_abstraction


def homing(drone_state:DroneStateForHoming,frame:Frame):
    min_actual = float("inf")
    closest_det = None
    for i in frame.detection:
        dist = detection_to_dist(drone_state,i)
        if dist < min_actual:
            min_actual = dist
            closest_det = i
        if min_actual <= MIN_SPRAY_ERROR:
            return DroneStateEnum.SPRAY

    if closest_det is None:
        db
        
        or min_actual > MAX_HOMING_DIST:
        return DroneStateEnum.GOTO

    dalt = -1
    if drone_state.altitude_rel_home < MIN_ALT + dalt:
        dalt = 0

    ned = detection_to_ned(drone_state, closest_det)
    telemetry_singlton.send_displacement_command_yaw_stay_same(ned[0], ned[1], dalt)
    return DroneStateEnum.HOMING
    
    
    
