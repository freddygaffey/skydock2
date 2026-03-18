"""
Mission to Video Parser

Reads a mission folder and stitches the frames into a video
with telemetry, detection, and FSM state overlays.

Usage:
    python mission_to_video.py <mission_folder>
    python mission_to_video.py 2026-02-06_18-46-11
"""

import sys
import os
import ast
import math
import cv2
import numpy as np
from pathlib import Path
from bisect import bisect_right


def parse_drone_state(mission_dir: Path) -> list[tuple[int, dict]]:
    """Parse drone_state.txt into list of (timestamp_ns, state_dict)."""
    entries = []
    path = mission_dir / "drone_state.txt"
    if not path.exists():
        print(f"Warning: {path} not found, skipping telemetry overlay")
        return entries

    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            comma_idx = line.index(",")
            timestamp_ns = int(line[:comma_idx])
            state_dict = ast.literal_eval(line[comma_idx + 1:])
            entries.append((timestamp_ns, state_dict))
    return entries


def parse_frames_txt(mission_dir: Path) -> list[tuple[int, list]]:
    """Parse frames.txt into list of (timestamp_ns, detections_list)."""
    entries = []
    path = mission_dir / "frames.txt"
    if not path.exists():
        print(f"Warning: {path} not found, skipping detection overlay")
        return entries

    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            frame_data = ast.literal_eval(line)
            entries.append((frame_data["time_ns"], frame_data["detections"]))
    return entries


def parse_fsm(mission_dir: Path) -> list[tuple[int, str]]:
    """Parse fsm.txt into list of (timestamp_ns, state_name)."""
    entries = []
    path = mission_dir / "fsm.txt"
    if not path.exists():
        print(f"Warning: {path} not found, skipping FSM overlay")
        return entries

    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            state_name = parts[0].replace("DroneStateEnum.", "")
            timestamp_ns = int(parts[1])
            entries.append((timestamp_ns, state_name))
    return entries


def get_frame_images(mission_dir: Path) -> list[tuple[int, Path]]:
    """Get sorted list of (timestamp_ns, image_path) from frames/ directory."""
    frames_dir = mission_dir / "frames"
    if not frames_dir.exists():
        print(f"Error: {frames_dir} not found")
        sys.exit(1)

    frames = []
    for img_file in frames_dir.iterdir():
        if img_file.suffix.lower() in (".jpg", ".jpeg", ".png"):
            timestamp_ns = int(img_file.stem)
            frames.append((timestamp_ns, img_file))

    frames.sort(key=lambda x: x[0])
    return frames


def lookup_nearest(entries: list[tuple[int, any]], timestamp_ns: int):
    """Find the entry with the closest timestamp <= given timestamp."""
    if not entries:
        return None
    timestamps = [e[0] for e in entries]
    idx = bisect_right(timestamps, timestamp_ns) - 1
    if idx < 0:
        idx = 0
    return entries[idx][1]


def draw_overlay(frame: np.ndarray, drone_state: dict | None,
                 detections: list | None, fsm_state: str | None,
                 elapsed_s: float) -> np.ndarray:
    """Draw telemetry, detections, and FSM state onto the frame."""
    h, w = frame.shape[:2]
    overlay = frame.copy()

    # Semi-transparent black bar at the top
    bar_height = 120
    cv2.rectangle(overlay, (0, 0), (w, bar_height), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)

    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.45
    color = (255, 255, 255)
    thickness = 1
    line_height = 18
    y_start = 16

    # Elapsed time
    mins = int(elapsed_s // 60)
    secs = elapsed_s % 60
    cv2.putText(frame, f"T+{mins:02d}:{secs:05.2f}", (8, y_start),
                font, font_scale, (0, 255, 255), thickness)

    # FSM state
    if fsm_state:
        state_color = {
            "OVERRIDE": (0, 0, 255),
            "SCAN": (255, 200, 0),
            "GOTO": (0, 200, 255),
            "HOMING": (255, 100, 0),
            "SPRAY": (0, 255, 0),
            "RTL": (200, 0, 255),
        }.get(fsm_state, (255, 255, 255))
        cv2.putText(frame, f"STATE: {fsm_state}", (w - 200, y_start),
                    font, 0.55, state_color, 2)

    # Drone telemetry
    if drone_state:
        y = y_start + line_height
        lat = drone_state.get("latitude", 0.0)
        lon = drone_state.get("longitude", 0.0)
        alt = drone_state.get("altitude_rel_home", 0.0)
        heading = drone_state.get("heading", 0.0)
        mode = drone_state.get("mode", "?")
        armed = drone_state.get("arm_state", False)
        vx = drone_state.get("velocity_x", 0.0)
        vy = drone_state.get("velocity_y", 0.0)
        speed = math.sqrt(vx**2 + vy**2)

        cv2.putText(frame, f"Mode: {mode}  {'ARMED' if armed else 'DISARMED'}",
                    (8, y), font, font_scale, color, thickness)
        y += line_height
        cv2.putText(frame, f"Lat: {lat:.7f}  Lon: {lon:.7f}",
                    (8, y), font, font_scale, color, thickness)
        y += line_height
        cv2.putText(frame, f"Alt: {alt:.1f}m  Hdg: {heading:.1f} deg",
                    (8, y), font, font_scale, color, thickness)
        y += line_height
        cv2.putText(frame, f"Speed: {speed:.1f} m/s",
                    (8, y), font, font_scale, color, thickness)

        # Autonomy indicator
        autonomy = drone_state.get("enable_homing_and_autonomy", False)
        auto_color = (0, 255, 0) if autonomy else (0, 0, 255)
        auto_text = "AUTO: ON" if autonomy else "AUTO: OFF"
        cv2.putText(frame, auto_text, (w - 200, y_start + line_height),
                    font, font_scale, auto_color, thickness)

    # Draw detection bounding boxes
    if detections:
        for det in detections:
            bbox = det.get("bbox", None)
            label = det.get("label", "?")
            conf = det.get("confidence", 0.0)
            if bbox:
                # bbox format: [(x1, y1), (x2, y2)]
                (x1, y1), (x2, y2) = bbox
                x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                det_text = f"{label} {conf:.0%}"
                cv2.putText(frame, det_text, (x1, y1 - 5),
                            font, font_scale, (0, 255, 0), thickness)

        # Detection count
        n = len(detections)
        cv2.putText(frame, f"Detections: {n}",
                    (w - 200, y_start + 2 * line_height),
                    font, font_scale, (0, 255, 0), thickness)

    return frame


def build_video(mission_dir: Path, output_path: Path, fps: float = 10.0):
    """Build the video from mission data."""
    print(f"Parsing mission data from: {mission_dir}")

    # Parse all data sources
    drone_states = parse_drone_state(mission_dir)
    frame_detections = parse_frames_txt(mission_dir)
    fsm_states = parse_fsm(mission_dir)
    frame_images = get_frame_images(mission_dir)

    if not frame_images:
        print("Error: No frame images found")
        sys.exit(1)

    print(f"  Drone state entries: {len(drone_states)}")
    print(f"  Frame detection entries: {len(frame_detections)}")
    print(f"  FSM state entries: {len(fsm_states)}")
    print(f"  Frame images: {len(frame_images)}")

    # Read first frame to get dimensions
    first_frame = cv2.imread(str(frame_images[0][1]))
    if first_frame is None:
        print(f"Error: Could not read {frame_images[0][1]}")
        sys.exit(1)
    h, w = first_frame.shape[:2]

    # Create video writer
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(output_path), fourcc, fps, (w, h))

    start_ns = frame_images[0][0]

    for i, (ts_ns, img_path) in enumerate(frame_images):
        frame = cv2.imread(str(img_path))
        if frame is None:
            print(f"  Warning: Could not read {img_path}, skipping")
            continue

        elapsed_s = (ts_ns - start_ns) / 1e9

        # Look up closest data for this frame's timestamp
        drone_state = lookup_nearest(drone_states, ts_ns)
        detections = lookup_nearest(frame_detections, ts_ns)
        fsm_state = lookup_nearest(fsm_states, ts_ns)

        # Draw overlay and write frame
        frame = draw_overlay(frame, drone_state, detections, fsm_state, elapsed_s)
        writer.write(frame)

        if (i + 1) % 10 == 0 or (i + 1) == len(frame_images):
            print(f"  Processed {i + 1}/{len(frame_images)} frames")

    writer.release()
    print(f"Video saved to: {output_path}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python mission_to_video.py <mission_folder>")
        print("Example: python mission_to_video.py 2026-02-06_18-46-11")
        sys.exit(1)

    mission_path = Path(sys.argv[1])

    # If relative path, look in project root
    if not mission_path.is_absolute():
        project_root = Path(__file__).parent
        mission_path = project_root / mission_path

    if not mission_path.exists():
        print(f"Error: Mission folder not found: {mission_path}")
        sys.exit(1)

    output_path = mission_path / "mission_video.mp4"
    build_video(mission_path, output_path)


if __name__ == "__main__":
    main()
