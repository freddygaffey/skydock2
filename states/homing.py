import time
import math

from telemetry import telemetry_singlton
from drone_state import DroneStateForHoming
from ai_class import Frame, Detection
from utils import detection_to_dist, detection_to_ned
from constants import MIN_ALT, MIN_SPRAY_ERROR, SIM_SPEED, TIME_WAIT_FOR_DET, MAX_HOMING_TIME, MAX_HOMING_ALT, MAX_HOMING_DIST
from states.enum import DroneStateEnum
from mission_logging import log_event

# Detection scoring knobs (tune in code, not JSON)
SCORE_CONF_MIDPOINT = 0.3      # sigmoid midpoint: confidence at this value scores ~0.5
SCORE_CONF_STEEPNESS = 10.0    # sigmoid steepness around midpoint
SCORE_CONF_FLOOR = 0.1         # ignore detections below this raw confidence
SCORE_BBOX_FRAC = 0.1          # bbox sqrt-area as fraction of image diag = full size_term
SCORE_ASPECT_MAX = 2.0         # bboxes more elongated than this are penalized
SCORE_ASPECT_PENALTY = 0.5     # multiplier applied when aspect ratio exceeds threshold
MIN_HOMING_SCORE = 0.05        # detections below this score are treated as no-detection


def score_detection(drone_state: DroneStateForHoming, det: Detection, max_dist_m: float) -> tuple[float, float]:
    """Multi-factor credibility score. Returns (score, dist_m). score in 0..~1.
    Combines confidence (sigmoid around SCORE_CONF_MIDPOINT), proximity (exp decay
    over max_dist_m), bbox size relative to image, and aspect-ratio sanity."""
    dist_m = detection_to_dist(drone_state, det)
    if det.confidence < SCORE_CONF_FLOOR or not math.isfinite(dist_m):
        return 0.0, dist_m

    conf_term = 1.0 / (1.0 + math.exp(-SCORE_CONF_STEEPNESS * (det.confidence - SCORE_CONF_MIDPOINT)))
    decay = max(max_dist_m / 3.0, 1.0)
    dist_term = math.exp(-dist_m / decay)

    p1, p2 = det.bbox
    bw = abs(p2[0] - p1[0])
    bh = abs(p2[1] - p1[1])
    image_diag_px = math.sqrt(drone_state.width**2 + drone_state.hight**2)
    size_term = min(1.0, math.sqrt(bw * bh) / max(image_diag_px * SCORE_BBOX_FRAC, 1.0))

    ar = max(bw, bh) / max(min(bw, bh), 1e-6)
    aspect_term = 1.0 if ar < SCORE_ASPECT_MAX else SCORE_ASPECT_PENALTY

    return conf_term * dist_term * size_term * aspect_term, dist_m


last_det_time = None
start_homing_time = None


def calc_speed(drone_state:DroneStateForHoming,det:Detection):
    N, E = detection_to_ned(drone_state, det)
    vN = max(-0.75, min(0.75, N))
    vE = max(-0.75, min(0.75, E))
    if drone_state.altitude_rel_home > MAX_HOMING_ALT:
        vD = 0.3
    elif drone_state.altitude_rel_home < MIN_ALT:
        vD = -0.3
    else:
        vD = 0.0
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

    # pick highest-scoring detection (combines confidence, proximity, bbox size, aspect)
    min_det = None
    min_dist = float('inf')
    best_score = 0.0
    for i in frame.detection:
        s, d = score_detection(drone_state, i, MAX_HOMING_DIST)
        if s > best_score:
            best_score = s
            min_dist = d
            min_det = i
    if best_score < MIN_HOMING_SCORE:
        min_det = None
        min_dist = float('inf')

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
            print("exceed max alt")
            log_event("homing_alt_cap", logger="homing", level="WARN",
                      drone_state=drone_state, frame=frame,
                      altitude_rel_home=float(drone_state.altitude_rel_home),
                      max_homing_alt=float(MAX_HOMING_ALT))
            telemetry_singlton.send_volocity_command_yaw_stay_same(0, 0, 0.1)  # move down
        else:
            telemetry_singlton.send_volocity_command_yaw_stay_same(0, 0, -0.2) # move up
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
            # return DroneStateEnum.SPRAY
            # todo: remove 
            return DroneStateEnum.HOMING
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

