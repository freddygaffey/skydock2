import time

from telemetry import telemetry_singlton
from drone_state import DroneStateForHoming
from ai_class import Frame, Detection
from utils import detection_to_dist, detection_to_ned
from constants import MIN_ALT, MIN_SPRAY_ERROR, SIM_SPEED, TIME_WAIT_FOR_DET, MAX_HOMING_TIME, MAX_HOMING_ALT
from states.enum import DroneStateEnum
from mission_logging import log_event

last_det_time = None
start_homing_time = None


def calc_speed(drone_state:DroneStateForHoming,det:Detection):
    N, E = detection_to_ned(drone_state, det)
    vN = max(-0.75, min(0.75, N))
    vE = max(-0.75, min(0.75, E))
    vD = 1.0 if drone_state.altitude_rel_home > MIN_ALT else 0.0
    return (vN, vE, vD)

    
def homing(drone_state:DroneStateForHoming,frame:Frame):
    # intate last_det_time
    global last_det_time
    if last_det_time is None:
        last_det_time = time.time()

    # intate total time homing
    global start_homing_time
    if start_homing_time is None:
        start_homing_time = time.time()

    # calulate closet detecion
    min_det = None
    min_dist = float('inf')
    for i in frame.detection:
        d = detection_to_dist(drone_state, i)
        if d < min_dist:
            min_dist = d
            min_det = i

    if min_det is not None:
        last_det_time = time.time()

    # check if weed still there was ever there
    if min_det is None and (time.time() - last_det_time) > TIME_WAIT_FOR_DET / SIM_SPEED:
        log_event("homing_give_up_no_det", logger="homing", level="WARN",
                  drone_state=drone_state, frame=frame,
                  elapsed_no_det_s=float(time.time() - last_det_time))
        last_det_time = None
        start_homing_time = None
        return DroneStateEnum.GOTO

    # move up to try and find weed (cap at MAX_HOMING_ALT)
    elif min_det is None:
        if drone_state.altitude_rel_home >= MAX_HOMING_ALT:
            log_event("homing_alt_cap", logger="homing", level="WARN",
                      drone_state=drone_state, frame=frame,
                      altitude_rel_home=float(drone_state.altitude_rel_home),
                      max_homing_alt=float(MAX_HOMING_ALT))
            telemetry_singlton.send_volocity_command_yaw_stay_same(0, 0, 0)  # hold alt
        else:
            telemetry_singlton.send_volocity_command_yaw_stay_same(0, 0, -1) # move up
        return DroneStateEnum.HOMING

    # stop it just sitting there
    if (time.time() - start_homing_time) > MAX_HOMING_TIME / SIM_SPEED:
        log_event("homing_give_up_timeout", logger="homing", level="WARN",
                  drone_state=drone_state, frame=frame,
                  elapsed_total_s=float(time.time() - start_homing_time),
                  min_dist_m=float(min_dist))
        last_det_time = None
        start_homing_time = None
        return DroneStateEnum.GOTO

    # spray weed
    if min_dist <= MIN_SPRAY_ERROR:
        # check alt
        if drone_state.altitude_rel_home <= MIN_ALT + 1:
            log_event("spray_ready", logger="spray", level="INFO",
                      drone_state=drone_state, frame=frame,
                      dist_horizontal_m=float(min_dist),
                      min_spray_error_m=float(MIN_SPRAY_ERROR),
                      closest_detection={"time_detected": min_det.time_ns})
            last_det_time = None
            start_homing_time = None
            return DroneStateEnum.SPRAY
        else:
            # the homing funcatin will handle this move the drone closer to the weed and down
            pass
    vel = calc_speed(drone_state, min_det)
    log_event("homing_tick", logger="homing", level="DEBUG",
              drone_state=drone_state, frame=frame,
              min_dist_m=float(min_dist), velocity_ned=list(vel),
              elapsed_total_s=float(time.time() - start_homing_time),
              elapsed_no_det_s=float(time.time() - last_det_time))
    telemetry_singlton.send_volocity_command_yaw_stay_same(*vel)
    return DroneStateEnum.HOMING

