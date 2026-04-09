"""Sweep camera yaw offset to find the best R_cam_to_body alignment.

Reads fsm_tick events from a real mission JSONL, re-projects all detections
with a range of yaw offsets, and computes mean error to nearest ground-truth
weed in real_missions/sv.json.

Usage:
    python tools/test_camera_orientation.py --mission rpi_missions/0006
    python tools/test_camera_orientation.py --mission rpi_missions/0006 --plot
"""

import argparse
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

# Allow importing from the repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils import haversine_distance

TRUTH_PATH = Path(__file__).resolve().parents[1] / "real_missions" / "sv.json"

CAMERA_FOV_X = 27.4
CAMERA_FOV_Y = 21.0
NUM_OF_PIX_X = 640
NUM_OF_PIX_Y = 640

fx = NUM_OF_PIX_X / (2 * np.tan(np.radians(CAMERA_FOV_X / 2)))
fy = NUM_OF_PIX_Y / (2 * np.tan(np.radians(CAMERA_FOV_Y / 2)))
cx = NUM_OF_PIX_X / 2
cy = NUM_OF_PIX_Y / 2


def project_detection(bbox, drone_state, R_cam_to_body):
    """Re-implementation of detection_to_ned with injectable R_cam_to_body."""
    px = (bbox[0][0] + bbox[1][0]) / 2
    py = (bbox[0][1] + bbox[1][1]) / 2

    x_cam = (px - cx) / fx
    y_cam = (py - cy) / fy

    cam_ray = np.array([x_cam, y_cam, 1.0])
    cam_ray /= np.linalg.norm(cam_ray)

    ray_body = R_cam_to_body @ cam_ray

    rot = drone_state.get("rotaion", {})
    roll = float(rot.get("x", 0))
    pitch = float(rot.get("y", 0))
    yaw = float(rot.get("z", 0))

    Rx = np.array([
        [1,  0,           0          ],
        [0,  np.cos(roll), -np.sin(roll)],
        [0,  np.sin(roll),  np.cos(roll)],
    ])
    Ry = np.array([
        [ np.cos(pitch), 0, np.sin(pitch)],
        [0,              1, 0             ],
        [-np.sin(pitch), 0, np.cos(pitch) ],
    ])
    Rz = np.array([
        [np.cos(yaw), -np.sin(yaw), 0],
        [np.sin(yaw),  np.cos(yaw), 0],
        [0,            0,           1],
    ])

    ray_NED = Rz @ Ry @ Rx @ ray_body

    rangefinder_m = float(drone_state.get("rangefinder_m", 0))
    altitude = float(drone_state.get("altitude_rel_home", 0))

    if rangefinder_m > 0.3:
        factor = rangefinder_m
    else:
        factor = altitude / max(ray_NED[2], 0.1)

    N = factor * ray_NED[0]
    E = factor * ray_NED[1]

    lat = drone_state["latitude"]
    lon = drone_state["longitude"]
    dlat = N / 111320
    dlon = E / (111320 * math.cos(math.radians(lat)))
    return lat + dlat, lon + dlon


def nearest_truth_error(pred_lat, pred_lon, truth_weeds):
    return min(
        haversine_distance(pred_lat, pred_lon, w["lat"], w["lon"])
        for w in truth_weeds
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mission", required=True, help="Path to mission directory, e.g. rpi_missions/0006")
    parser.add_argument("--plot", action="store_true", help="Show matplotlib plot")
    args = parser.parse_args()

    mission_path = Path(args.mission)
    if not mission_path.is_absolute():
        mission_path = Path(__file__).resolve().parents[1] / mission_path
    jsonl_path = mission_path / "mission.jsonl"
    if not jsonl_path.exists():
        sys.exit(f"Not found: {jsonl_path}")

    truth = json.loads(TRUTH_PATH.read_text())
    truth_weeds = truth["weed_locations"]
    print(f"Loaded {len(truth_weeds)} truth weeds from {TRUTH_PATH.name}")

    # Extract (drone_state, bbox) pairs from fsm_tick events
    samples = []
    with open(jsonl_path) as f:
        for line in f:
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("event") != "fsm_tick":
                continue
            ds = e.get("drone_state")
            frame = e.get("frame", {})
            detections = frame.get("detections", [])
            if not ds or not detections:
                continue
            for det in detections:
                bbox = det.get("bbox")
                if bbox and len(bbox) == 2:
                    samples.append((ds, bbox))

    if not samples:
        sys.exit("No detections found in mission JSONL.")
    print(f"Found {len(samples)} detections to sweep over.")

    # Pre-filter: at 0° offset, keep only detections that project within MAX_PREFILTER_M
    # of any truth weed.  False positives (grass etc.) swamp the signal otherwise.
    MAX_PREFILTER_M = 20.0
    R_identity = np.eye(3)
    filtered_samples = []
    for ds, bbox in samples:
        try:
            lat, lon = project_detection(bbox, ds, R_identity)
            if nearest_truth_error(lat, lon, truth_weeds) <= MAX_PREFILTER_M:
                filtered_samples.append((ds, bbox))
        except Exception:
            pass
    print(f"After pre-filter (within {MAX_PREFILTER_M}m of truth at 0°): {len(filtered_samples)} detections")
    if not filtered_samples:
        print("WARNING: no detections within pre-filter range — using all samples")
        filtered_samples = samples

    # --- Sweep GPS lag using dead-reckoning ---
    # GPS is on the boot clock; attitude/detection are on the wall clock. We can't
    # compute the exact lag, so sweep it and find the minimum error.
    print("\n--- GPS lag sweep (dead-reckoning correction with R=identity) ---")
    lag_candidates = [i * 0.05 for i in range(0, 41)]  # 0.0 to 2.0s in 50ms steps
    lag_errors = []
    R_identity = np.eye(3)
    for lag_s in lag_candidates:
        errors = []
        for ds, bbox in filtered_samples:
            try:
                # Dead-reckon lat/lon forward by lag_s using logged NED velocity
                vx = float(ds.get("velocity_x", 0))  # m/s North
                vy = float(ds.get("velocity_y", 0))  # m/s East
                lat0 = float(ds["latitude"])
                lon0 = float(ds["longitude"])
                dlat = (vx * lag_s) / 111320
                dlon = (vy * lag_s) / (111320 * math.cos(math.radians(lat0)))
                corrected_ds = dict(ds)
                corrected_ds["latitude"] = lat0 + dlat
                corrected_ds["longitude"] = lon0 + dlon
                lat, lon = project_detection(bbox, corrected_ds, R_identity)
                errors.append(nearest_truth_error(lat, lon, truth_weeds))
            except Exception:
                pass
        lag_errors.append(sum(errors) / len(errors) if errors else float("inf"))
    best_lag_idx = int(np.argmin(lag_errors))
    best_lag = lag_candidates[best_lag_idx]
    print(f"Best GPS lag: {best_lag:.2f}s (mean error: {lag_errors[best_lag_idx]:.2f} m)")
    print(f"  lag  err(m)")
    for lag_s, err in zip(lag_candidates, lag_errors):
        marker = " <--" if lag_s == best_lag else ""
        print(f"  {lag_s:.2f}   {err:.2f}{marker}")

    degrees = range(-180, 181)
    mean_errors = []

    for deg in degrees:
        yaw_rad = np.radians(deg)
        R = np.array([
            [np.cos(yaw_rad), -np.sin(yaw_rad), 0],
            [np.sin(yaw_rad),  np.cos(yaw_rad), 0],
            [0,                0,                1],
        ])
        errors = []
        for ds, bbox in filtered_samples:
            try:
                lat, lon = project_detection(bbox, ds, R)
                err = nearest_truth_error(lat, lon, truth_weeds)
                errors.append(err)
            except Exception:
                pass
        mean_errors.append(sum(errors) / len(errors) if errors else float("inf"))

    best_idx = int(np.argmin(mean_errors))
    best_deg = list(degrees)[best_idx]
    best_err = mean_errors[best_idx]

    print(f"\nBest camera yaw offset: {best_deg}° (mean error: {best_err:.2f} m)")
    print(f"Worst offset:           {list(degrees)[int(np.argmax(mean_errors))]}° (mean error: {max(mean_errors):.2f} m)")

    # Print table around the best
    print("\n  deg   mean_err(m)")
    for deg, err in zip(degrees, mean_errors):
        if abs(deg - best_deg) <= 15:
            marker = " <--" if deg == best_deg else ""
            print(f"  {deg:4d}   {err:8.2f}{marker}")

    # --- Bias analysis at the best offset ---
    print("\n--- Bias vector at best offset ---")
    yaw_rad = np.radians(best_deg)
    R_best = np.array([
        [np.cos(yaw_rad), -np.sin(yaw_rad), 0],
        [np.sin(yaw_rad),  np.cos(yaw_rad), 0],
        [0,                0,                1],
    ])
    north_offsets = []
    east_offsets = []
    for ds, bbox in filtered_samples:
        try:
            pred_lat, pred_lon = project_detection(bbox, ds, R_best)
            # Find nearest truth weed
            best_weed = min(truth_weeds, key=lambda w: haversine_distance(pred_lat, pred_lon, w["lat"], w["lon"]))
            dN = (pred_lat - best_weed["lat"]) * 111320
            dE = (pred_lon - best_weed["lon"]) * 111320 * math.cos(math.radians(pred_lat))
            north_offsets.append(dN)
            east_offsets.append(dE)
        except Exception:
            pass
    if north_offsets:
        mn = sum(north_offsets) / len(north_offsets)
        me = sum(east_offsets) / len(east_offsets)
        mag = (mn**2 + me**2) ** 0.5
        bearing = math.degrees(math.atan2(me, mn)) % 360
        print(f"  Mean N offset: {mn:+.2f} m")
        print(f"  Mean E offset: {me:+.2f} m")
        print(f"  Magnitude:     {mag:.2f} m  @ {bearing:.0f}° (from N)")

    if args.plot:
        try:
            import matplotlib.pyplot as plt
            plt.figure(figsize=(10, 4))
            plt.plot(list(degrees), mean_errors)
            plt.axvline(best_deg, color="red", linestyle="--", label=f"best={best_deg}°")
            plt.xlabel("Camera yaw offset (degrees)")
            plt.ylabel("Mean error to nearest truth weed (m)")
            plt.title("Camera orientation sweep")
            plt.legend()
            plt.tight_layout()
            plt.show()
        except ImportError:
            print("matplotlib not available, skipping plot.")


if __name__ == "__main__":
    main()
