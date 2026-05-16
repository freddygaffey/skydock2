import time
import math

from telemetry import telemetry_singlton
from drone_state import DroneStateForHoming
from ai_class import Frame, Detection
from utils import detection_to_dist, detection_to_ned
from constants import MIN_ALT, MIN_SPRAY_ERROR, SIM_SPEED, TIME_WAIT_FOR_DET, MAX_HOMING_TIME, MAX_HOMING_ALT, MAX_HOMING_DIST
from states.enum import DroneStateEnum
from mission_logging import log_event

# MIN_HOMING_SCORE = 0.05        # detections below this score are treated as no-detection
# def score_detection(drone_state: DroneStateForHoming, det: Detection, max_dist_m: float) -> tuple[float, float]:
#     """Multi-factor credibility score. Returns (score, dist_m). score in 0..~1.
#     Combines confidence (sigmoid around SCORE_CONF_MIDPOINT), proximity (exp decay
#     over max_dist_m), bbox size relative to image, and aspect-ratio sanity."""
#
#     SCORE_CONF_MIDPOINT = 0.3      # sigmoid midpoint: confidence at this value scores ~0.5
#     SCORE_CONF_STEEPNESS = 10.0    # sigmoid steepness around midpoint
#     SCORE_CONF_FLOOR = 0.1         # ignore detections below this raw confidence
#     SCORE_BBOX_FRAC = 0.1          # bbox sqrt-area as fraction of image diag = full size_term
#     SCORE_ASPECT_MAX = 2.0         # bboxes more elongated than this are penalized
#     SCORE_ASPECT_PENALTY = 0.5     # multiplier applied when aspect ratio exceeds threshold
#
#     dist_m = detection_to_dist(drone_state, det)
#     if det.confidence < SCORE_CONF_FLOOR or not math.isfinite(dist_m):
#         return 0.0, dist_m
#
#     conf_term = 1.0 / (1.0 + math.exp(-SCORE_CONF_STEEPNESS * (det.confidence - SCORE_CONF_MIDPOINT)))
#     decay = max(max_dist_m / 3.0, 1.0)
#     dist_term = math.exp(-dist_m / decay)
#
#     p1, p2 = det.bbox
#     bw = abs(p2[0] - p1[0])
#     bh = abs(p2[1] - p1[1])
#     image_diag_px = math.sqrt(drone_state.width**2 + drone_state.hight**2)
#     size_term = min(1.0, math.sqrt(bw * bh) / max(image_diag_px * SCORE_BBOX_FRAC, 1.0))
#
#     ar = max(bw, bh) / max(min(bw, bh), 1e-6)
#     aspect_term = 1.0 if ar < SCORE_ASPECT_MAX else SCORE_ASPECT_PENALTY
#
#     return conf_term * dist_term * size_term * aspect_term, dist_m

last_det_time = None
start_homing_time = None
_last_alt_warn = {}  # key -> last time printed

def _alt_warn(key: str, msg: str, period_s: float = 5.0):
    now = time.time()
    if now - _last_alt_warn.get(key, 0.0) >= period_s:
        _last_alt_warn[key] = now
        print(msg)
    
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
    best_det = None
    min_dist = float('inf')
    for i in frame.detection:
        d = detection_to_dist(drone_state, i)
        if d < min_dist:
            min_dist = d
            best_det = i

    # stop it just sitting there check timout
    if (time.time() - start_homing_time) > MAX_HOMING_TIME / SIM_SPEED:
        log_event("homing_give_up_timeout", logger="homing", level="WARN",
                  drone_state=drone_state, frame=frame,
                  elapsed_total_s=float(time.time() - start_homing_time),
                  min_dist_m=float(min_dist))
        last_det_time = None
        start_homing_time = None
        telemetry_singlton.stop_volocity_command()
        return DroneStateEnum.GOTO

######## If detection is None
    if best_det is not None:
        last_det_time = time.time()

    # This block tests to ensure that if a weed has been lost for more than
    # TIME_WAIT_FOR_DET seconds, it doesn't continue searching
    if best_det is None and (time.time() - last_det_time) > TIME_WAIT_FOR_DET / SIM_SPEED:
        log_event("homing_give_up_no_det", logger="homing", level="WARN",
                  drone_state=drone_state, frame=frame,
                  elapsed_no_det_s=float(time.time() - last_det_time))
        last_det_time = None
        start_homing_time = None
        telemetry_singlton.stop_volocity_command()
        return DroneStateEnum.GOTO

    # move up to try and find weed (cap at MAX_HOMING_ALT)
    elif best_det is None:
        if drone_state.altitude_rel_home >= MAX_HOMING_ALT:
            _alt_warn("max", "exceed max alt")
            log_event("homing_alt_cap", logger="homing", level="WARN",
                      drone_state=drone_state, frame=frame,
                      altitude_rel_home=float(drone_state.altitude_rel_home),
                      max_homing_alt=float(MAX_HOMING_ALT))
            telemetry_singlton.send_volocity_command_yaw_stay_same(0, 0, 0.5)  # move down
        else:
            telemetry_singlton.send_volocity_command_yaw_stay_same(0, 0, -0.4) # move up
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
            telemetry_singlton.stop_volocity_command()
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
    telemetry_singlton.send_volocity_command_yaw_stay_same(mx=vN,my=vE,mz=vD)

    log_event("homing_tick", logger="homing", level="DEBUG",
              drone_state=drone_state, frame=frame,
              min_dist_m=float(min_dist), velocity_ned=[vN, vE, vD],
              elapsed_total_s=float(time.time() - start_homing_time),
              elapsed_no_det_s=float(time.time() - last_det_time))

    return DroneStateEnum.HOMING

