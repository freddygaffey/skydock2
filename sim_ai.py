import threading
import time
import math
import random
import numpy as np

from telemetry import telemetry_singlton
from ai_class import ai_storage_singleton, Detection, Frame
from drone_state import DroneStateForHoming
from mission_logging import log_event
from constants import SIM_SPEED, SIM_AI_ENABLE_IMPERFECTIONS


# Camera parameters – must match utils.detection_to_ned
CAMERA_FOV_X = 27.4  # degrees
CAMERA_FOV_Y = 21.0  # degrees
NUM_OF_PIX_X = 640
NUM_OF_PIX_Y = 640
SIM_AI_FPS = 30.0

# Pixel jitter (Gaussian std-dev in pixels) applied to bbox center.
SIM_AI_PIXEL_NOISE_STD_PX = 2.0

# Relative jitter (Gaussian std-dev as fraction of size) applied to bbox width/height.
# Example: 0.08 means ~8% std-dev.
SIM_AI_SIZE_NOISE_STD_FRAC = 0.08

# Probability to drop a true detection (false negative), per detection per frame.
SIM_AI_MISS_PROB = 0.06

# Probability to add a false positive, per frame.
SIM_AI_FALSE_POS_PROB = 0.03

# Probability to output the wrong label for a real detection, per detection per frame.
SIM_AI_WRONG_LABEL_PROB = 0.04

# Confidence noise (Gaussian std-dev) and bounds.
SIM_AI_CONFIDENCE_MEAN = 0.90
SIM_AI_CONFIDENCE_NOISE_STD = 0.06
SIM_AI_CONFIDENCE_MIN = 0.05
SIM_AI_CONFIDENCE_MAX = 0.99

# Deterministic randomness for repeatable sims.
SIM_AI_RANDOM_SEED = 1337

# Extra pixel noise per rad/s of angular rate (simulates motion blur).
SIM_AI_ROTATION_NOISE_SCALE_PX_PER_RADS = 30.0

FX = NUM_OF_PIX_X / (2 * math.tan(math.radians(CAMERA_FOV_X / 2)))
FY = NUM_OF_PIX_Y / (2 * math.tan(math.radians(CAMERA_FOV_Y / 2)))
CX = NUM_OF_PIX_X / 2.0
CY = NUM_OF_PIX_Y / 2.0


def _vision_params():
    # Keep this JSON-serializable (for mission_logging)
    return {
        "camera": {
            "fov_x_deg": CAMERA_FOV_X,
            "fov_y_deg": CAMERA_FOV_Y,
            "width_px": NUM_OF_PIX_X,
            "height_px": NUM_OF_PIX_Y,
            "fx": FX,
            "fy": FY,
            "cx": CX,
            "cy": CY,
        },
        "sim_ai": {
            "fps": SIM_AI_FPS,
            "enable_imperfections": SIM_AI_ENABLE_IMPERFECTIONS,
            "pixel_noise_std_px": SIM_AI_PIXEL_NOISE_STD_PX,
            "size_noise_std_frac": SIM_AI_SIZE_NOISE_STD_FRAC,
            "miss_prob": SIM_AI_MISS_PROB,
            "false_pos_prob": SIM_AI_FALSE_POS_PROB,
            "wrong_label_prob": SIM_AI_WRONG_LABEL_PROB,
            "confidence_mean": SIM_AI_CONFIDENCE_MEAN,
            "confidence_noise_std": SIM_AI_CONFIDENCE_NOISE_STD,
            "confidence_min": SIM_AI_CONFIDENCE_MIN,
            "confidence_max": SIM_AI_CONFIDENCE_MAX,
            "random_seed": SIM_AI_RANDOM_SEED,
        },
        "model": {
            "weed_diameter_m": 0.5,
            "bbox_min_px": 8.0,
            "bbox_max_px_frac_of_width": 0.8,
        },
    }


def _visible_weed_detections(
    drone_state: DroneStateForHoming,
    weed_locations: list[dict],  # [{"id": int, "lat": float, "lon": float}, ...]
) -> list[Detection]:
    """
    Given current drone state and weed GPS locations,
    return Detection objects for weeds that are visible in the camera.
    """
    if drone_state is None or drone_state.altitude_rel_home <= 0:
        return []

    lat0 = drone_state.latitude
    lon0 = drone_state.longitude
    alt = drone_state.altitude_rel_home

    # Bounding circle of the full image footprint: use half-diagonal FOV
    # so weeds at the corners of the wider X-axis aren't culled early.
    # The pixel-bounds check below handles precise clipping.
    half_diag_deg = math.sqrt((CAMERA_FOV_X / 2) ** 2 + (CAMERA_FOV_Y / 2) ** 2)
    max_ground_radius = alt * math.tan(math.radians(half_diag_deg))

    detections: list[Detection] = []

    # Hard-code weed physical diameter (meters) for all weeds
    diameter_m = 0.5

    for w in weed_locations:
        lat, lon, wid = w["lat"], w["lon"], w["id"]

        # GPS delta to local N/E offsets (same idea as utils.detection_to_latlon)
        dlat = lat - lat0
        dlon = lon - lon0

        N = dlat * 111_320.0
        E = dlon * 111_320.0 * math.cos(math.radians(lat0))

        dist = math.hypot(N, E)
        if dist > max_ground_radius:
            continue  # not in view on the ground

        # Rotate NED offset into body/camera frame using full attitude.
        # Mirrors the inverse of utils.detection_to_ned (Rz@Ry@Rx body→NED),
        # so sim-generated pixels round-trip correctly through detection_to_latlon.
        roll  = drone_state.rotaion.x
        pitch = drone_state.rotaion.y
        yaw   = drone_state.rotaion.z

        Rx = np.array([[1, 0, 0],
                       [0,  np.cos(roll), -np.sin(roll)],
                       [0,  np.sin(roll),  np.cos(roll)]])
        Ry = np.array([[ np.cos(pitch), 0, np.sin(pitch)],
                       [0, 1, 0],
                       [-np.sin(pitch), 0, np.cos(pitch)]])
        Rz = np.array([[np.cos(yaw), -np.sin(yaw), 0],
                       [np.sin(yaw),  np.cos(yaw), 0],
                       [0, 0, 1]])

        # NED vector from drone to weed; z is positive-down so weed is +alt below.
        ned = np.array([N, E, alt])
        # Inverse of (Rz@Ry@Rx) is (Rz@Ry@Rx).T = Rx.T @ Ry.T @ Rz.T
        ray_body = (Rx.T @ Ry.T @ Rz.T) @ ned

        if ray_body[2] <= 0:
            continue  # weed is behind or above the camera

        x_cam = ray_body[0] / ray_body[2]
        y_cam = ray_body[1] / ray_body[2]

        u = FX * x_cam + CX
        v = FY * y_cam + CY

        # Skip if outside image
        if not (0 <= u < NUM_OF_PIX_X and 0 <= v < NUM_OF_PIX_Y):
            continue

        # Bbox size based on weed physical diameter and altitude:
        # angular size ≈ diameter / altitude, pixel size ≈ focal * angular_size
        # Clamp to reasonable limits so it never disappears / fills whole frame
        min_px = 8.0
        max_px = NUM_OF_PIX_X * 0.8

        size_x = max(min_px, min(max_px, FX * (diameter_m / alt)))
        size_y = max(min_px, min(max_px, FY * (diameter_m / alt)))

        half_w = size_x / 2.0
        half_h = size_y / 2.0
        x_min = max(0, u - half_w)
        y_min = max(0, v - half_h)
        x_max = min(NUM_OF_PIX_X - 1, u + half_w)
        y_max = min(NUM_OF_PIX_Y - 1, v + half_h)

        bbox = [(x_min, y_min), (x_max, y_max)]

        det = Detection(
            label="sports ball",  # kept by Frame.add_detection
            confidence=0.9,
            bbox=bbox,
            truth_id=wid,
        )
        detections.append(det)

    return detections


def run_sim_ai(weed_locations: list[dict]):
    """
    Start a background 30 FPS loop:
    - Reads telemetry_singlton.drone_state
    - Computes visible weeds
    - Updates ai_storage_singleton with Frame(detections)
    """

    # Log sim vision parameters once per mission
    try:
        log_event(
            "sim_vision_params",
            logger="sim_ai",
            level="INFO",
            vision=_vision_params(),
        )
    except Exception:
        # Logging should never crash sim AI
        pass

    def _loop():
        dt = 1.0 / SIM_AI_FPS  # FPS
        start = time.perf_counter()
        frame_idx = 0
        rng = random.Random(SIM_AI_RANDOM_SEED)

        wrong_labels = ("person", "car", "bicycle", "dog", "cat", "chair")

        while True:
            # Do work for this frame
            drone_state = getattr(telemetry_singlton, "drone_state", None)
            if drone_state is not None:
                dets = _visible_weed_detections(drone_state, weed_locations)

                if SIM_AI_ENABLE_IMPERFECTIONS:
                    noisy: list[Detection] = []

                    for d in dets:
                        # False negative: sometimes miss a real detection
                        if rng.random() < SIM_AI_MISS_PROB:
                            continue

                        # Extract bbox
                        (x_min, y_min), (x_max, y_max) = d.bbox
                        w = max(1.0, x_max - x_min)
                        h = max(1.0, y_max - y_min)
                        cx = (x_min + x_max) / 2.0
                        cy = (y_min + y_max) / 2.0

                        # Jitter center and size; scale noise by angular rate magnitude
                        omega = math.sqrt(
                            drone_state.rotaion.dx**2 +
                            drone_state.rotaion.dy**2 +
                            drone_state.rotaion.dz**2
                        )
                        effective_pixel_noise = (
                            SIM_AI_PIXEL_NOISE_STD_PX
                            + omega * SIM_AI_ROTATION_NOISE_SCALE_PX_PER_RADS
                        )
                        cx += rng.gauss(0.0, effective_pixel_noise)
                        cy += rng.gauss(0.0, effective_pixel_noise)

                        w *= max(0.2, 1.0 + rng.gauss(0.0, SIM_AI_SIZE_NOISE_STD_FRAC))
                        h *= max(0.2, 1.0 + rng.gauss(0.0, SIM_AI_SIZE_NOISE_STD_FRAC))

                        # Rebuild + clamp bbox to image bounds
                        x_min2 = cx - w / 2.0
                        y_min2 = cy - h / 2.0
                        x_max2 = cx + w / 2.0
                        y_max2 = cy + h / 2.0

                        x_min2 = max(0.0, min(float(NUM_OF_PIX_X - 2), x_min2))
                        y_min2 = max(0.0, min(float(NUM_OF_PIX_Y - 2), y_min2))
                        x_max2 = max(x_min2 + 1.0, min(float(NUM_OF_PIX_X - 1), x_max2))
                        y_max2 = max(y_min2 + 1.0, min(float(NUM_OF_PIX_Y - 1), y_max2))

                        d.bbox = [(x_min2, y_min2), (x_max2, y_max2)]

                        # Confidence is not always accurate
                        conf = rng.gauss(SIM_AI_CONFIDENCE_MEAN, SIM_AI_CONFIDENCE_NOISE_STD)
                        conf = max(SIM_AI_CONFIDENCE_MIN, min(SIM_AI_CONFIDENCE_MAX, conf))
                        d.confidence = float(conf)

                        # Sometimes wrong class label
                        if rng.random() < SIM_AI_WRONG_LABEL_PROB:
                            d.label = rng.choice(wrong_labels)

                        noisy.append(d)

                    # False positives: sometimes hallucinate an object
                    if rng.random() < SIM_AI_FALSE_POS_PROB:
                        w = rng.uniform(12.0, 90.0)
                        h = rng.uniform(12.0, 90.0)
                        cx = rng.uniform(w / 2.0, NUM_OF_PIX_X - 1 - w / 2.0)
                        cy = rng.uniform(h / 2.0, NUM_OF_PIX_Y - 1 - h / 2.0)
                        bbox = [(cx - w / 2.0, cy - h / 2.0), (cx + w / 2.0, cy + h / 2.0)]
                        fp = Detection(
                            label=rng.choice(wrong_labels),
                            confidence=float(
                                max(
                                    SIM_AI_CONFIDENCE_MIN,
                                    min(SIM_AI_CONFIDENCE_MAX, rng.gauss(0.45, 0.15)),
                                )
                            ),
                            bbox=bbox,
                        )
                        noisy.append(fp)

                    dets = noisy

                frame = Frame(dets, drone_state=drone_state)
                ai_storage_singleton.set_latest_frame(frame)

            # Schedule next frame based on absolute time
            frame_idx += 1
            next_time = start + frame_idx * dt / SIM_SPEED

            now = time.perf_counter()
            sleep_time = next_time - now
            if sleep_time > 0:
                time.sleep(sleep_time)
            # if sleep_time <= 0: we're behind; loop immediately and try to catch up

    threading.Thread(target=_loop, daemon=True).start()
