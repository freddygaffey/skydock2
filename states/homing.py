import time
import math

from telemetry import telemetry_singleton
from drone_state import DroneStateForHoming
from ai_class import Frame
from utils import detection_to_dist, detection_to_ned
from constants import MIN_ALT, MIN_SPRAY_ERROR, SIM_SPEED, TIME_WAIT_FOR_DET, MAX_HOMING_TIME, MAX_HOMING_ALT
from states.enum import DroneStateEnum
from mission_logging import log_event

# NOTE: a commented-out multi-factor detection-scoring prototype (score_detection)
# previously lived here. Its design is captured in docs/refactor_plan.md (Phase 4).

last_det_time = None
start_homing_time = None
_last_alt_warn = {}  # key -> last time printed

def _alt_warn(key: str, msg: str, period_s: float = 5.0):
    now = time.time()
    if now - _last_alt_warn.get(key, 0.0) >= period_s:
        _last_alt_warn[key] = now
        print(msg)
    
def homing(drone_state:DroneStateForHoming,frame:Frame):
    """Close in on the weed under the camera using velocity control.

    Picks the nearest detection and drives horizontal velocity toward it
    (vN/vE = copysign(min(0.7*sqrt|offset|, 2 m/s))), descending toward MIN_ALT.
    With no detection it climbs to search up to MAX_HOMING_ALT. Gives up to GOTO
    on either timeout (MAX_HOMING_TIME total, or TIME_WAIT_FOR_DET since the last
    detection). Returns SPRAY once within MIN_SPRAY_ERROR and low enough (unless
    force_homing keeps it homing). Uses module-level timers last_det_time /
    start_homing_time, reset on every exit.
    """
    # intate last_det_time
    global last_det_time
    if last_det_time is None:
        last_det_time = time.time()

    # intate total time homing
    global start_homing_time
    if start_homing_time is None:
        start_homing_time = time.time()

    # calulate closet detecion
    best_det = None
    min_dist = float('inf')
    for i in frame.detection:
        d = detection_to_dist(drone_state, i)
        if d < min_dist:
            min_dist = d
            best_det = i

    # stop it just sitting there check timout
    if (time.time() - start_homing_time) > MAX_HOMING_TIME / SIM_SPEED:
        log_event("homing_give_up_timeout", logger="homing", level="WARNING",
                  drone_state=drone_state, frame=frame,
                  elapsed_total_s=float(time.time() - start_homing_time),
                  min_dist_m=float(min_dist))
        last_det_time = None
        start_homing_time = None
        telemetry_singleton.stop_velocity_command()
        return DroneStateEnum.GOTO

######## If detection is None
    if best_det is not None:
        last_det_time = time.time()

    # This block tests to ensure that if a weed has been lost for more than
    # TIME_WAIT_FOR_DET seconds, it doesn't continue searching
    if best_det is None and (time.time() - last_det_time) > TIME_WAIT_FOR_DET / SIM_SPEED:
        log_event("homing_give_up_no_det", logger="homing", level="WARNING",
                  drone_state=drone_state, frame=frame,
                  elapsed_no_det_s=float(time.time() - last_det_time))
        last_det_time = None
        start_homing_time = None
        telemetry_singleton.stop_velocity_command()
        return DroneStateEnum.GOTO

    # move up to try and find weed (cap at MAX_HOMING_ALT)
    elif best_det is None:
        if drone_state.altitude_rel_home >= MAX_HOMING_ALT:
            _alt_warn("max", "exceed max alt")
            log_event("homing_alt_cap", logger="homing", level="WARNING",
                      drone_state=drone_state, frame=frame,
                      altitude_rel_home=float(drone_state.altitude_rel_home),
                      max_homing_alt=float(MAX_HOMING_ALT))
            telemetry_singleton.send_velocity_command_yaw_stay_same(0, 0, 0.5)  # move down
        else:
            telemetry_singleton.send_velocity_command_yaw_stay_same(0, 0, -0.4) # move up
        return DroneStateEnum.HOMING

####### Detection is there
    # spray weed
    if min_dist <= MIN_SPRAY_ERROR:
        # if low enough
        if drone_state.altitude_rel_home <= MIN_ALT + 1:
            log_event("spray_ready", logger="spray", level="INFO",
                      drone_state=drone_state, frame=frame,
                      dist_horizontal_m=float(min_dist),
                      min_spray_error_m=float(MIN_SPRAY_ERROR),
                      closest_detection={"time_detected": best_det.time_ns})
            # reset things
            last_det_time = None
            start_homing_time = None
            telemetry_singleton.stop_velocity_command()
            if drone_state.force_homing: 
                return DroneStateEnum.HOMING
            else:
                return DroneStateEnum.SPRAY
        else:
            ...
            # this needs to pass then it will run homing as nomal
            # the homing will make it move down
            
    N, E = detection_to_ned(drone_state, best_det)


    vN = math.copysign(min(0.7*abs(N)**0.5,2),N) # just got of desmos
    vE = math.copysign(min(0.7*abs(E)**0.5,2),E) # just got of desmos

    if drone_state.altitude_rel_home > MAX_HOMING_ALT:
        _alt_warn("max", "exceed max alt")
        vD = 0.3
    elif drone_state.altitude_rel_home < MIN_ALT:
        _alt_warn("min", "exceed min alt")
        vD = -0.3
    else:
        vD = 0.3
    telemetry_singleton.send_velocity_command_yaw_stay_same(mx=vN,my=vE,mz=vD)

    log_event("homing_tick", logger="homing", level="DEBUG",
              drone_state=drone_state, frame=frame,
              min_dist_m=float(min_dist), velocity_ned=[vN, vE, vD],
              elapsed_total_s=float(time.time() - start_homing_time),
              elapsed_no_det_s=float(time.time() - last_det_time))

    return DroneStateEnum.HOMING

