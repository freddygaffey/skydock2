import threading
import time
import math
import random
import numpy as np
import os

from telemetry import telemetry_singleton
from ai_class import ai_storage_singleton, Detection, Frame
from drone_state import DroneStateForHoming
from mission_logging import log_event, get_mission_dir
import constants


# Simulated camera mirrors DroneStateForHoming: resolution from its
# width/height defaults, FOV/intrinsics from its lens constants — the same
# source utils.detection_to_ned uses, so sim pixels round-trip exactly.
# Frame rate comes from constants.TARGET_FPS, shared with ai_callback.
NUM_OF_PIX_X = DroneStateForHoming.width
NUM_OF_PIX_Y = DroneStateForHoming.height

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

def _vision_params(drone_state: DroneStateForHoming):
    # Keep this JSON-serializable (for mission_logging)
    fov_x = drone_state.fov_x_deg
    fov_y = drone_state.fov_y_deg
    return {
        "camera": {
            "fov_x_deg": fov_x,
            "fov_y_deg": fov_y,
            "width_px": NUM_OF_PIX_X,
            "height_px": NUM_OF_PIX_Y,
            "fx": NUM_OF_PIX_X / (2 * math.tan(math.radians(fov_x / 2))),
            "fy": NUM_OF_PIX_Y / (2 * math.tan(math.radians(fov_y / 2))),
            "cx": NUM_OF_PIX_X / 2.0,
            "cy": NUM_OF_PIX_Y / 2.0,
        },
        "sim_ai": {
            "fps": constants.TARGET_FPS,
            "enable_imperfections": constants.SIM_AI_ENABLE_IMPERFECTIONS,
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


# Hard-coded weed physical diameter (metres) — used for both detection bbox sizing
# and the rendered blob size, so the drawn weed matches the box around it.
WEED_DIAMETER_M = 0.5


def _camera_intrinsics(drone_state: DroneStateForHoming):
    """fx, fy, cx, cy in the sim pixel space (NUM_OF_PIX_X × NUM_OF_PIX_Y).

    Derived from drone_state's FOV/lens — the same values utils.detection_to_ned
    uses — so sim pixels round-trip exactly through detection_to_latlon.
    """
    fov_x = drone_state.fov_x_deg
    fov_y = drone_state.fov_y_deg
    fx = NUM_OF_PIX_X / (2 * math.tan(math.radians(fov_x / 2)))
    fy = NUM_OF_PIX_Y / (2 * math.tan(math.radians(fov_y / 2)))
    cx = NUM_OF_PIX_X / 2.0
    cy = NUM_OF_PIX_Y / 2.0
    return fx, fy, cx, cy


def _project_latlon_to_pixel(drone_state: DroneStateForHoming, lat: float, lon: float,
                             fx: float, fy: float, cx: float, cy: float):
    """Project a ground GPS point to a (u, v) pixel, or None if not in front of the camera.

    Single source of truth for sim projection — used by both detection generation and
    frame rendering. Mirrors the inverse of utils.detection_to_ned (Rz@Ry@Rx body→NED).
    """
    lat0 = drone_state.latitude
    lon0 = drone_state.longitude
    alt = drone_state.altitude_rel_home

    N = (lat - lat0) * 111_320.0
    E = (lon - lon0) * 111_320.0 * math.cos(math.radians(lat0))

    roll  = drone_state.rotation.x
    pitch = drone_state.rotation.y
    yaw   = drone_state.rotation.z

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
        return None  # weed is behind or above the camera

    u = fx * (ray_body[0] / ray_body[2]) + cx
    v = fy * (ray_body[1] / ray_body[2]) + cy
    return (u, v)


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

    alt = drone_state.altitude_rel_home
    fx, fy, cx, cy = _camera_intrinsics(drone_state)

    # Bounding circle of the full image footprint: use half-diagonal FOV
    # so weeds at the corners of the wider X-axis aren't culled early.
    # The pixel-bounds check below handles precise clipping.
    fov_x = drone_state.fov_x_deg
    fov_y = drone_state.fov_y_deg
    half_diag_deg = math.sqrt((fov_x / 2) ** 2 + (fov_y / 2) ** 2)
    max_ground_radius = alt * math.tan(math.radians(half_diag_deg))

    detections: list[Detection] = []

    for w in weed_locations:
        lat, lon, wid = w["lat"], w["lon"], w["id"]

        # Cheap ground-distance cull before the full projection.
        N = (lat - drone_state.latitude) * 111_320.0
        E = (lon - drone_state.longitude) * 111_320.0 * math.cos(math.radians(drone_state.latitude))
        if math.hypot(N, E) > max_ground_radius:
            continue  # not in view on the ground

        proj = _project_latlon_to_pixel(drone_state, lat, lon, fx, fy, cx, cy)
        if proj is None:
            continue
        u, v = proj

        # Skip if outside image
        if not (0 <= u < NUM_OF_PIX_X and 0 <= v < NUM_OF_PIX_Y):
            continue

        # Bbox size based on weed physical diameter and altitude:
        # angular size ≈ diameter / altitude, pixel size ≈ focal * angular_size
        # Clamp to reasonable limits so it never disappears / fills whole frame
        min_px = 8.0
        max_px = NUM_OF_PIX_X * 0.8

        size_x = max(min_px, min(max_px, fx * (WEED_DIAMETER_M / alt)))
        size_y = max(min_px, min(max_px, fy * (WEED_DIAMETER_M / alt)))

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


def _render_frame(drone_state: DroneStateForHoming, dets: list[Detection],
                  true_weeds: list[dict], predicted_weeds: list[tuple]):
    """Render a synthetic camera frame (BGR uint8) at the sim resolution.

    Layers (per Fred): ground, true weeds (filled green blobs — what the camera
    'sees'), predicted/clustered weeds (cross markers; grey if sprayed), and the
    detection boxes (red rectangles + label). Mirrors the real camera image so the
    saved JPEG flows through the same pipeline as real frames.
    """
    import cv2

    H, W = NUM_OF_PIX_Y, NUM_OF_PIX_X
    img = np.full((H, W, 3), (60, 90, 60), dtype=np.uint8)  # ground (BGR olive)

    fx, fy, cx, cy = _camera_intrinsics(drone_state)
    alt = drone_state.altitude_rel_home

    if alt > 0:
        # True weeds: filled green blobs sized like the detection bbox.
        blob_r = max(3, int(0.5 * fx * (WEED_DIAMETER_M / alt)))
        for w in true_weeds:
            proj = _project_latlon_to_pixel(drone_state, w["lat"], w["lon"], fx, fy, cx, cy)
            if proj is None:
                continue
            u, v = proj
            if 0 <= u < W and 0 <= v < H:
                cv2.circle(img, (int(u), int(v)), blob_r, (40, 170, 40), -1)

        # Predicted (clustered) weeds: cross markers; grey once sprayed.
        for lat, lon, sprayed in predicted_weeds:
            proj = _project_latlon_to_pixel(drone_state, lat, lon, fx, fy, cx, cy)
            if proj is None:
                continue
            u, v = proj
            if 0 <= u < W and 0 <= v < H:
                color = (120, 120, 120) if sprayed else (220, 140, 0)  # BGR: grey / blue
                cv2.drawMarker(img, (int(u), int(v)), color, cv2.MARKER_CROSS, 24, 2)

    # Detection boxes: red rectangles + label/confidence.
    for d in dets:
        (x0, y0), (x1, y1) = d.bbox
        cv2.rectangle(img, (int(x0), int(y0)), (int(x1), int(y1)), (0, 0, 220), 2)
        cv2.putText(img, f"{d.label} {d.confidence:.2f}", (int(x0), int(max(0, y0 - 4))),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 220), 1, cv2.LINE_AA)

    size = constants.SIM_AI_RENDER_SIZE
    if size and size > 0 and (W, H) != (size, size):
        img = cv2.resize(img, (size, size), interpolation=cv2.INTER_AREA)
    return img


def run_sim_ai(weed_locations: list[dict]):
    """
    Start a background 30 FPS loop:
    - Reads telemetry_singleton.drone_state
    - Computes visible weeds
    - Updates ai_storage_singleton with Frame(detections)
    """

    # Sim renders detections in NUM_OF_PIX_X × NUM_OF_PIX_Y pixel space — make
    # the live drone_state advertise the same resolution so utils.detection_to_ned
    # uses matching intrinsics.
    ds = getattr(telemetry_singleton, "drone_state", None)
    if ds is not None:
        ds.width = NUM_OF_PIX_X
        ds.height = NUM_OF_PIX_Y

    # Log sim vision parameters once per mission
    try:
        log_event(
            "sim_vision_params",
            logger="sim_ai",
            level="INFO",
            vision=_vision_params(ds if ds is not None else DroneStateForHoming()),
        )
    except Exception:
        # Logging should never crash sim AI
        pass

    # Frame rendering setup: write synthetic JPEGs to missions/NNNN/frames/{time_ns}.jpg,
    # the same path/naming the real pipeline uses, so sim and real share one image path.
    frames_dir = None
    if constants.SIM_AI_RENDER_FRAMES:
        mdir = get_mission_dir()
        if mdir is not None:
            frames_dir = mdir / "frames"
            frames_dir.mkdir(parents=True, exist_ok=True)

    def _loop():
        import cv2
        from pathlib import Path  # noqa: F401 (kept local; frames_dir is a Path)

        # Predicted (clustered) weeds live in the mission DB; refresh on a slow cadence
        # rather than every frame. Imported here (not at module top) so it loads after
        # DB.set_db_path() — see init order in CLAUDE.md.
        try:
            from DB_abstraction import db_abstraction
        except Exception:
            db_abstraction = None
        predicted_weeds: list[tuple] = []
        last_pred_refresh = 0.0

        dt = 1.0 / constants.TARGET_FPS
        start = time.perf_counter()
        frame_idx = 0
        rng = random.Random(SIM_AI_RANDOM_SEED)

        # Save at most SIM_AI_RENDER_MAX_FPS JPEGs per sim-second: render every Nth loop.
        save_stride = max(1, round(constants.TARGET_FPS / max(1e-6, constants.SIM_AI_RENDER_MAX_FPS)))

        wrong_labels = ("person", "car", "bicycle", "dog", "cat", "chair")

        while True:
            # Do work for this frame
            drone_state = getattr(telemetry_singleton, "drone_state", None)
            if drone_state is not None:
                dets = _visible_weed_detections(drone_state, weed_locations)

                if constants.SIM_AI_ENABLE_IMPERFECTIONS:
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
                            drone_state.rotation.dx**2 +
                            drone_state.rotation.dy**2 +
                            drone_state.rotation.dz**2
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

                    # False positives: sometimes hallucinate a ball. Labelled
                    # "sports ball" because that's the only kind of FP that
                    # survives Frame.add_detection — same as on real hardware.
                    if rng.random() < SIM_AI_FALSE_POS_PROB:
                        w = rng.uniform(12.0, 90.0)
                        h = rng.uniform(12.0, 90.0)
                        cx = rng.uniform(w / 2.0, NUM_OF_PIX_X - 1 - w / 2.0)
                        cy = rng.uniform(h / 2.0, NUM_OF_PIX_Y - 1 - h / 2.0)
                        bbox = [(cx - w / 2.0, cy - h / 2.0), (cx + w / 2.0, cy + h / 2.0)]
                        fp = Detection(
                            label="sports ball",
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

                # Stamp every detection in this frame with one timestamp, and name the
                # JPEG with the same value. analysis.build_frame_events attaches detections
                # to a frame by matching detection.time_detected to the jpeg stem, so they
                # must agree for sim frames to flow through the real-mission code path.
                frame_ts = time.time_ns()
                for d in dets:
                    d.time_ns = frame_ts

                # Route through add_detection so sim detections pass the same
                # label gate as the real pipeline (ai_callback.py). Wrong-label
                # noise gets dropped here, exactly as it would on the drone.
                frame = Frame([], drone_state=drone_state)
                for d in dets:
                    frame.add_detection(d)

                # Render + save the synthetic camera frame (gated weeds need altitude).
                # Throttled to SIM_AI_RENDER_MAX_FPS so long missions don't emit >100k JPEGs.
                if (frames_dir is not None and drone_state.altitude_rel_home > 0
                        and frame_idx % save_stride == 0):
                    if (time.perf_counter() - last_pred_refresh) > 0.5 and db_abstraction is not None:
                        try:
                            predicted_weeds = [
                                (w.lat, w.lon, bool(w.sprayed))
                                for w in db_abstraction.get_all_weeds()
                            ]
                        except Exception:
                            predicted_weeds = []
                        last_pred_refresh = time.perf_counter()

                    img = _render_frame(drone_state, frame.detection, weed_locations, predicted_weeds)

                    # the time_ns.jpg
                    out_path = frames_dir / f"{frame_ts}.jpg"
                    cv2.imwrite(str(out_path), img)
                    frame.photo_path = str(out_path)

                    # frame latest this will get overwritten 
                    # this is a atomic write
                    
                    
                    out_path = frames_dir / "tmp_latest.jpg"
                    cv2.imwrite(str(out_path), img)
                    os.replace(f"{frames_dir}/tmp_latest.jpg",f"{frames_dir}/latest.jpg")

                    # Rendering must never crash sim AI.
                    pass

                ai_storage_singleton.set_latest_frame(frame)

            # Schedule next frame based on absolute time
            frame_idx += 1
            next_time = start + frame_idx * dt / constants.SIM_SPEED

            now = time.perf_counter()
            sleep_time = next_time - now
            if sleep_time > 0:
                time.sleep(sleep_time)
            # if sleep_time <= 0: we're behind; loop immediately and try to catch up

    threading.Thread(target=_loop, daemon=True).start()
