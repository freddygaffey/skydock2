from telemetry import telemetry_singlton
from drone_state import DroneStateForHoming
from ai_class import Frame
from DB_abstraction import db_abstraction, Weed
from utils import detection_to_latlon, haversine_distance, detection_to_ned
from constants import MIN_SPRAY_ERROR
from states.enum import DroneStateEnum
from mission_logging import log_event


def spraying(drone_state:DroneStateForHoming,frame:Frame):
    sprayed = False
    closest_weed = db_abstraction.get_closest_weed(drone_state)
    if closest_weed is None:
        return DroneStateEnum.RTL

    for i in frame.detection:
        NE = detection_to_ned(drone_state,i)
        dist = (NE[0]**2 + NE[1]**2)**0.5
        if dist <= MIN_SPRAY_ERROR:
            sprayed = True
            print("sprayed a weed")
            log_event(
                "spray_attempt",
                logger="spray",
                level="INFO",
                drone_state=drone_state,
                frame=frame,
                dist_horizontal_m=float(dist),
                min_spray_error_m=float(MIN_SPRAY_ERROR),
                within_min_spray_error=True,
                target_weed={"id": closest_weed.id, "lat": closest_weed.lat, "lon": closest_weed.lon},
                triggering_detection={"time_detected": i.time_ns, "label": i.label, "confidence": i.confidence},
            )
            db_abstraction.mark_weed_sprayed(closest_weed)
    if not sprayed:
        print("no weed found")
        log_event(
            "spray_miss",
            logger="spray",
            level="WARNING",
            drone_state=drone_state,
            frame=frame,
            min_spray_error_m=float(MIN_SPRAY_ERROR),
            target_weed={"id": closest_weed.id, "lat": closest_weed.lat, "lon": closest_weed.lon},
        )
        db_abstraction.mark_weed_traveled(closest_weed)

    return DroneStateEnum.GOTO

