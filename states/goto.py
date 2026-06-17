import time

from telemetry import telemetry_singleton
from drone_state import DroneStateForHoming
from ai_class import Frame
from DB_abstraction import db_abstraction
from utils import haversine_distance
from constants import GOTO_ALT, MAX_HOMING_DIST
from states.enum import DroneStateEnum
import states.shared_data as shared_data


def goto(drone_state:DroneStateForHoming,frame:Frame):
    """Navigate to the closest unsprayed weed.

    Returns RTL when no unsprayed weeds remain. If the closest weed is within
    MAX_HOMING_DIST, marks it traveled and returns HOMING; otherwise flies
    toward it at GOTO_ALT and stays in GOTO.
    """
    shared_data.last_goto_time = time.time()
    weed = db_abstraction.get_closest_weed(drone_state)
    if not weed:
        return DroneStateEnum.RTL
    dist = haversine_distance(weed.lat,weed.lon,drone_state.latitude,drone_state.longitude)
    if dist < MAX_HOMING_DIST:
        db_abstraction.mark_weed_traveled(weed)
        return DroneStateEnum.HOMING
    telemetry_singleton.fly_to_point(weed.lat,weed.lon,GOTO_ALT)
    return DroneStateEnum.GOTO
