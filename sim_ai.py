import threading
import time
import math

from telemetry import telemetry_singlton
from ai_class import ai_storage_singleton, Detection, Frame
from drone_state import DroneStateForHoming


# Camera parameters – must match utils.detection_to_ned
CAMERA_FOV_X = 27.4  # degrees
CAMERA_FOV_Y = 21.0  # degrees
NUM_OF_PIX_X = 640
NUM_OF_PIX_Y = 640

FX = NUM_OF_PIX_X / (2 * math.tan(math.radians(CAMERA_FOV_X / 2)))
FY = NUM_OF_PIX_Y / (2 * math.tan(math.radians(CAMERA_FOV_Y / 2)))
CX = NUM_OF_PIX_X / 2.0
CY = NUM_OF_PIX_Y / 2.0


def _visible_weed_detections(
    drone_state: DroneStateForHoming,
    weed_locations: list[list[float]],  # [[lat, lon], ...]
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

    # Approx ground footprint radius in meters from vertical FOV
    max_ground_radius = alt * math.tan(math.radians(CAMERA_FOV_Y / 2))

    detections: list[Detection] = []

    # Hard-code weed physical diameter (meters) for all weeds
    diameter_m = 0.5

    for lat, lon in weed_locations:

        # GPS delta to local N/E offsets (same idea as utils.detection_to_latlon)
        dlat = lat - lat0
        dlon = lon - lon0

        N = dlat * 111_320.0
        E = dlon * 111_320.0 * math.cos(math.radians(lat0))

        dist = math.hypot(N, E)
        if dist > max_ground_radius:
            continue  # not in view on the ground

        # Approximate pinhole projection: x_cam ≈ N/alt, y_cam ≈ E/alt
        x_cam = N / alt
        y_cam = E / alt

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
        )
        detections.append(det)

    return detections


def run_sim_ai(weed_locations: list[list[float]]):
    """
    Start a background 30 FPS loop:
    - Reads telemetry_singlton.drone_state
    - Computes visible weeds
    - Updates ai_storage_singleton with Frame(detections)
    """

    def _loop():
        dt = 1.0 / 30.0  # 30 FPS
        start = time.perf_counter()
        frame_idx = 0

        while True:
            # Do work for this frame
            drone_state = getattr(telemetry_singlton, "drone_state", None)
            if drone_state is not None:
                dets = _visible_weed_detections(drone_state, weed_locations)
                frame = Frame(dets)
                ai_storage_singleton.set_latest_frame(frame)

            # Schedule next frame based on absolute time
            frame_idx += 1
            next_time = start + frame_idx * dt

            now = time.perf_counter()
            sleep_time = next_time - now
            if sleep_time > 0:
                time.sleep(sleep_time)
            # if sleep_time <= 0: we're behind; loop immediately and try to catch up

    threading.Thread(target=_loop, daemon=True).start()
