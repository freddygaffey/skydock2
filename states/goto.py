from dataclasses import dataclass
from ai_class import Detection

from telemetry import telemetry_singlton
from drone_state import DroneStateForHoming
from ai_class import Frame
from DB_abstraction import db_abstraction, Weed
from utils import detection_to_latlon, haversine_distance, detection_to_ned
from fsm import DroneStateEnum
from states.constants import GOTO_ALT, MAX_HOMING_DIST


def goto(drone_state:DroneStateForHoming,frame:Frame):
    weed = db_abstraction.get_closest_weed(drone_state)
    if not weed:
        return DroneStateEnum.RTL
    if haversine_distance(weed.lat,weed.lon,drone_state.latitude,drone_state.longitude) < MAX_HOMING_DIST:
        return DroneStateEnum.HOMING
    telemetry_singlton.fly_to_point(weed.lat,weed.lon,GOTO_ALT)
    return DroneStateEnum.GOTO
