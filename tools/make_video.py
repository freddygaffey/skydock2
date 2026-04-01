"""
Make Mission Video
==================
Stitches JPEG frames from a mission's ``frames/`` directory into an MP4
with telemetry, detection bboxes, FSM state, and (for sim missions) a
running accuracy overlay.

Usage
-----
    python tools/make_video.py missions/0026
    python tools/make_video.py rpi_missions/0006
    python tools/make_video.py missions/0026 --fps 15 --output my_video.mp4

**Timing (default):** JPEG filenames must have numeric stems that sort in capture order
(typically ``time_ns``). Each frame is shown for the **real time** until the next frame
(irregular spacing is preserved). The last frame uses the same duration as the previous
gap (minimum 0.05s).

**Fixed FPS:** pass ``--fps N`` to use equal time per frame (legacy behaviour).

Output is saved as ``mission_video.mp4``. Real-time mode encodes directly with FFmpeg
(H.264). Fixed-FPS mode uses OpenCV ``mp4v`` then FFmpeg transcode to H.264 for browsers.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
import tempfile
from bisect import bisect_right
from pathlib import Path
from typing import Any

import cv2
import numpy as np


# ── JSONL helpers ─────────────────────────────────────────────────────────────

def iter_events(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


# ── Timestamp lookup ──────────────────────────────────────────────────────────

def nearest_by_ts(sorted_ts: list[int], sorted_vals: list[Any], ts_ns: int) -> Any | None:
    if not sorted_ts:
        return None
    idx = bisect_right(sorted_ts, ts_ns) - 1
    if idx < 0:
        idx = 0
    if idx + 1 < len(sorted_ts):
        if abs(sorted_ts[idx + 1] - ts_ns) < abs(sorted_ts[idx] - ts_ns):
            idx += 1
    return sorted_vals[idx]


# ── Accuracy helpers (mirrors tools/sim_accuracy.py) ──────────────────────────

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def match_accuracy(preds: list[dict], truth: list[dict], thresh_m: float) -> tuple[int, int, int]:
    used: set[int] = set()
    tp = fp = 0
    for p in preds:
        best_i, best_d = None, float("inf")
        for i, t in enumerate(truth):
            if i in used:
                continue
            d = haversine_m(p["lat"], p["lon"], t["lat"], t["lon"])
            if d < best_d:
                best_d, best_i = d, i
        if best_i is not None and best_d <= thresh_m:
            tp += 1
            used.add(best_i)
        else:
            fp += 1
    fn = len(truth) - len(used)
    return tp, fp, fn


# ── Overlay drawing ──────────────────────────────────────────────────────��────

FSM_COLORS = {
    "OVERRIDE": (0, 0, 255),
    "SCAN":     (0, 200, 255),
    "GOTO":     (255, 200, 0),
    "HOMING":   (0, 100, 255),
    "SPRAY":    (0, 255, 0),
    "RTL":      (200, 0, 255),
}


def draw_overlay(
    frame: np.ndarray,
    drone_state: dict | None,
    detections: list | None,
    fsm_state: str | None,
    elapsed_s: float,
    accuracy: dict | None = None,
) -> np.ndarray:
    h, w = frame.shape[:2]
    overlay = frame.copy()

    bar_height = 130
    cv2.rectangle(overlay, (0, 0), (w, bar_height), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)

    font = cv2.FONT_HERSHEY_SIMPLEX
    fs = 0.45
    white = (255, 255, 255)
    th = 1
    lh = 18
    y = 16

    # Elapsed time
    mins = int(elapsed_s // 60)
    secs = elapsed_s % 60
    cv2.putText(frame, f"T+{mins:02d}:{secs:05.2f}", (8, y), font, fs, (0, 255, 255), th)

    # FSM state (top-right)
    if fsm_state:
        state_clean = fsm_state.replace("DroneStateEnum.", "").split(".")[-1]
        sc = FSM_COLORS.get(state_clean.upper(), white)
        cv2.putText(frame, f"STATE: {state_clean}", (w - 210, y), font, 0.55, sc, 2)

    # Telemetry
    if drone_state:
        y += lh
        lat  = drone_state.get("latitude", 0.0)
        lon  = drone_state.get("longitude", 0.0)
        alt  = drone_state.get("altitude_rel_home", 0.0)
        hdg  = drone_state.get("heading", 0.0)
        mode = drone_state.get("mode", "?")
        armed = drone_state.get("arm_state", False)
        vx   = drone_state.get("velocity_x", 0.0)
        vy   = drone_state.get("velocity_y", 0.0)
        rng  = drone_state.get("rangefinder_m")
        speed = math.sqrt(vx ** 2 + vy ** 2)
        auto = drone_state.get("enable_homing_and_autonomy", False)

        cv2.putText(frame, f"Mode: {mode}  {'ARMED' if armed else 'DISARMED'}", (8, y), font, fs, white, th)
        auto_c = (0, 255, 0) if auto else (0, 0, 255)
        cv2.putText(frame, "AUTO: ON" if auto else "AUTO: OFF", (w - 210, y), font, fs, auto_c, th)
        y += lh
        cv2.putText(frame, f"Lat: {lat:.7f}  Lon: {lon:.7f}", (8, y), font, fs, white, th)
        y += lh
        cv2.putText(frame, f"Alt: {alt:.1f}m  Hdg: {hdg:.1f}°  Spd: {speed:.1f}m/s", (8, y), font, fs, white, th)
        if rng is not None:
            y += lh
            cv2.putText(frame, f"Rangefinder: {rng:.2f}m", (8, y), font, fs, (180, 255, 180), th)

    # Detection bboxes
    if detections:
        for det in detections:
            bbox = det.get("bbox")
            label = det.get("label", "?")
            conf = det.get("confidence", 0.0)
            if bbox and len(bbox) == 2:
                (x1, y1_d), (x2, y2_d) = bbox
                x1, y1_d, x2, y2_d = int(x1), int(y1_d), int(x2), int(y2_d)
                cv2.rectangle(frame, (x1, y1_d), (x2, y2_d), (0, 255, 0), 2)
                cv2.putText(frame, f"{label} {conf:.0%}", (x1, y1_d - 5), font, fs, (0, 255, 0), th)
        cv2.putText(frame, f"Detections: {len(detections)}",
                    (w - 210, 16 + 2 * lh), font, fs, (0, 255, 0), th)

    # Accuracy panel (sim only) — bottom-right corner
    if accuracy:
        tp = accuracy["tp"]
        fp = accuracy["fp"]
        fn = accuracy["fn"]
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec  = tp / (tp + fn) if (tp + fn) else 0.0
        lines = [
            f"TP:{tp}  FP:{fp}  FN:{fn}",
            f"P:{prec:.0%}  R:{rec:.0%}",
        ]
        box_w, box_h = 180, 46
        bx, by = w - box_w - 8, h - box_h - 8
        cv2.rectangle(frame, (bx - 4, by - 4), (w - 4, h - 4), (0, 0, 0), -1)
        cv2.rectangle(frame, (bx - 4, by - 4), (w - 4, h - 4), (80, 80, 80), 1)
        for i, txt in enumerate(lines):
            cv2.putText(frame, txt, (bx, by + 16 + i * lh), font, fs, (255, 230, 100), th)

    return frame


# ── Mission parsing ───────────────────────────────────────────────────────────

def parse_mission(mission_dir: Path) -> dict:
    log_path = mission_dir / "mission.jsonl"
    if not log_path.exists():
        print(f"Error: {log_path} not found")
        sys.exit(1)

    is_sim = False
    sim_truth_file = None
    weed_match_m = 0.5

    fsm_ticks_ts: list[int] = []
    fsm_ticks_data: list[dict] = []

    fsm_trans_ts: list[int] = []
    fsm_trans_state: list[str] = []

    weed_events_ts: list[int] = []
    weed_events_data: list[dict] = []

    start_ts_ns: int | None = None

    for ev in iter_events(log_path):
        event = ev.get("event", "")

        if event == "mission_start":
            is_sim = ev.get("is_sim", False)
            sim_truth_file = ev.get("sim_truth_file")
            weed_match_m = float(ev.get("weed_match_m", 0.5))

        elif event == "fsm_tick":
            ts = ev.get("time_ns")
            if ts is not None:
                ts = int(ts)
                if start_ts_ns is None:
                    start_ts_ns = ts
                fsm_ticks_ts.append(ts)
                fsm_ticks_data.append(ev)

        elif event == "fsm_transition":
            ts = ev.get("time_ns")
            if ts is not None:
                state = (ev.get("state_to") or ev.get("state") or "").replace("DroneStateEnum.", "").split(".")[-1]
                fsm_trans_ts.append(int(ts))
                fsm_trans_state.append(state)

        elif event == "weed_detected":
            ts = ev.get("time_ns") or ev.get("ts")
            lat = ev.get("lat") or (ev.get("weed") or {}).get("lat")
            lon = ev.get("lon") or (ev.get("weed") or {}).get("lon")
            if ts is not None and lat is not None and lon is not None:
                weed_events_ts.append(int(float(ts)) if isinstance(ts, str) else int(ts))
                weed_events_data.append({"lat": float(lat), "lon": float(lon)})

    return {
        "is_sim": is_sim,
        "sim_truth_file": sim_truth_file,
        "weed_match_m": weed_match_m,
        "fsm_ticks_ts": fsm_ticks_ts,
        "fsm_ticks_data": fsm_ticks_data,
        "fsm_trans_ts": fsm_trans_ts,
        "fsm_trans_state": fsm_trans_state,
        "weed_events_ts": weed_events_ts,
        "weed_events_data": weed_events_data,
        "start_ts_ns": start_ts_ns,
    }


def get_frame_images(mission_dir: Path) -> list[tuple[int, Path]]:
    frames_dir = mission_dir / "frames"
    if not frames_dir.exists():
        print(f"Error: {frames_dir} not found — no frames to process")
        sys.exit(1)
    frames = []
    for f in frames_dir.iterdir():
        if f.suffix.lower() in (".jpg", ".jpeg") and f.stem.isdigit():
            frames.append((int(f.stem), f))
    frames.sort()
    return frames


def _infer_seconds_per_stem_unit(stems: list[int]) -> float:
    """Convert numeric filename stem deltas to seconds (stems sorted ascending)."""
    if len(stems) < 2:
        return 1e-9
    gaps = [stems[i + 1] - stems[i] for i in range(len(stems) - 1) if stems[i + 1] >= stems[i]]
    if not gaps:
        return 1e-9
    med = sorted(gaps)[len(gaps) // 2]
    if med >= 1_000_000:
        return 1e-9  # nanoseconds
    if med >= 1_000:
        return 1e-6  # microseconds
    if med >= 1:
        return 1e-3  # milliseconds
    return 1e-9


def _frame_durations_seconds(stems: list[int], spu: float) -> list[float]:
    """Seconds each frame stays visible (length == len(stems))."""
    n = len(stems)
    if n == 0:
        return []
    if n == 1:
        return [1.0]
    min_d, max_d = 0.001, 300.0
    out: list[float] = []
    for i in range(n - 1):
        raw = (stems[i + 1] - stems[i]) * spu
        d = max(min_d, min(max_d, raw if raw > 0 else min_d))
        out.append(d)
    last = out[-1]
    out.append(max(min_d, min(max_d, last)))
    return out


def load_truth(sim_data_dir: Path, truth_filename: str) -> list[dict] | None:
    path = sim_data_dir / truth_filename
    if not path.exists():
        print(f"Warning: truth file not found: {path} — skipping accuracy overlay")
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    raw = data.get("weed_locations", [])
    out = []
    for w in raw:
        if isinstance(w, dict):
            out.append({"lat": float(w["lat"]), "lon": float(w["lon"])})
        else:
            out.append({"lat": float(w[0]), "lon": float(w[1])})
    return out


# ── Web-friendly encode ───────────────────────────────────────────────────────
# OpenCV's mp4v (MPEG-4 Part 2) often fails in HTML5 <video> (Firefox: unsupported
# format/MIME). Browsers expect H.264 (AVC) + yuv420p in MP4.


def resolve_ffmpeg_exe() -> str | None:
    """System ffmpeg first, then imageio-ffmpeg's bundled binary (pip install)."""
    w = shutil.which("ffmpeg")
    if w:
        return w
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def compose_frame(
    img_path: Path,
    ts_ns: int,
    data: dict,
    start_ns: int,
    truth: list[dict] | None,
) -> np.ndarray | None:
    """Load JPEG, apply overlay, return BGR image or None if unreadable."""
    frame = cv2.imread(str(img_path))
    if frame is None:
        return None
    elapsed_s = (ts_ns - start_ns) / 1e9
    tick = nearest_by_ts(data["fsm_ticks_ts"], data["fsm_ticks_data"], ts_ns)
    drone_state = tick.get("drone_state") if tick else None
    fr_obj = (tick.get("frame") or {}) if tick else {}
    detections = fr_obj.get("detections") or []
    fsm_state = nearest_by_ts(data["fsm_trans_ts"], data["fsm_trans_state"], ts_ns)
    accuracy = None
    if truth is not None:
        preds_so_far = [
            data["weed_events_data"][j]
            for j, t in enumerate(data["weed_events_ts"])
            if t <= ts_ns
        ]
        tp, fp, fn = match_accuracy(preds_so_far, truth, data["weed_match_m"])
        accuracy = {"tp": tp, "fp": fp, "fn": fn}
    return draw_overlay(frame, drone_state, detections, fsm_state, elapsed_s, accuracy)


def transcode_h264_for_web(path: Path) -> bool:
    """Replace *path* with an H.264 yuv420p + faststart MP4 suitable for browsers."""
    ffmpeg = resolve_ffmpeg_exe()
    if not ffmpeg:
        print(
            "Error: no ffmpeg executable. Install ffmpeg (e.g. apt install ffmpeg) "
            "or: pip install imageio-ffmpeg"
        )
        return False
    tmp = path.with_name(path.stem + "._h264_tmp.mp4")
    r = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(path),
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-an",
            str(tmp),
        ],
        capture_output=True,
        text=True,
        timeout=7200,
    )
    if r.returncode != 0 or not tmp.is_file():
        err = (r.stderr or r.stdout or "").strip()
        print(f"Error: ffmpeg transcode failed ({r.returncode}). {err[:800]}")
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        return False
    tmp.replace(path)
    return True


# ── Main ──────────────────────────────────────────────────────────────────────


def build_video_fixed_fps(mission_dir: Path, output_path: Path, fps: float):
    """Equal time per frame (legacy). OpenCV mp4v then H.264 transcode."""
    print(f"Parsing: {mission_dir}")
    data = parse_mission(mission_dir)
    frame_images = get_frame_images(mission_dir)

    if not frame_images:
        print("Error: no JPEG frames found")
        sys.exit(1)

    print(f"  Frames: {len(frame_images)}")
    print(f"  FSM ticks: {len(data['fsm_ticks_ts'])}")
    print(f"  FSM transitions: {len(data['fsm_trans_ts'])}")
    print(f"  Mode: fixed FPS  {fps}")

    truth: list[dict] | None = None
    if data["is_sim"] and data["sim_truth_file"]:
        sim_data_dir = mission_dir.parent.parent / "sim_data"
        truth = load_truth(sim_data_dir, data["sim_truth_file"])
        if truth:
            print(f"  Truth weeds: {len(truth)}  (thresh {data['weed_match_m']}m)")

    start_ns = data["start_ts_ns"] or frame_images[0][0]

    first = compose_frame(frame_images[0][1], frame_images[0][0], data, start_ns, truth)
    if first is None:
        print(f"Error: could not read {frame_images[0][1]}")
        sys.exit(1)
    h, w = first.shape[:2]

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(output_path), fourcc, fps, (w, h))

    for i, (ts_ns, img_path) in enumerate(frame_images):
        frame = compose_frame(img_path, ts_ns, data, start_ns, truth)
        if frame is None:
            print(f"  Warning: could not read {img_path}, skipping")
            continue
        writer.write(frame)
        if (i + 1) % 50 == 0 or (i + 1) == len(frame_images):
            print(f"  {i + 1}/{len(frame_images)} frames processed")

    writer.release()
    if not transcode_h264_for_web(output_path):
        print(
            "Error: could not produce browser-compatible H.264 MP4 "
            "(OpenCV output is MPEG-4 Part 2 and will not play in Firefox / most browsers)."
        )
        sys.exit(1)
    print(f"Video saved (H.264, web-ready): {output_path}")


def build_video_realtime(mission_dir: Path, output_path: Path):
    """Wall-clock timing from sorted JPEG stems; FFmpeg concat → H.264."""
    ffmpeg = resolve_ffmpeg_exe()
    if not ffmpeg:
        print("Error: no ffmpeg (required for real-time video). Install ffmpeg or pip install imageio-ffmpeg")
        sys.exit(1)

    print(f"Parsing: {mission_dir}")
    data = parse_mission(mission_dir)
    frame_images = get_frame_images(mission_dir)

    if not frame_images:
        print("Error: no JPEG frames found")
        sys.exit(1)

    kept: list[tuple[int, Path]] = []
    for ts_ns, img_path in frame_images:
        if cv2.imread(str(img_path)) is not None:
            kept.append((ts_ns, img_path))
    if not kept:
        print("Error: no readable JPEG frames")
        sys.exit(1)

    stems = [t for t, _ in kept]
    spu = _infer_seconds_per_stem_unit(stems)
    durations = _frame_durations_seconds(stems, spu)
    total_s = sum(durations)

    print(f"  Frames: {len(kept)} readable  ({len(frame_images)} on disk)")
    print(f"  FSM ticks: {len(data['fsm_ticks_ts'])}")
    print(f"  FSM transitions: {len(data['fsm_trans_ts'])}")
    print(f"  Mode: real-time  (~{total_s:.1f}s wall time from frame gaps, stem scale ~{spu:g} s/unit)")

    truth: list[dict] | None = None
    if data["is_sim"] and data["sim_truth_file"]:
        sim_data_dir = mission_dir.parent.parent / "sim_data"
        truth = load_truth(sim_data_dir, data["sim_truth_file"])
        if truth:
            print(f"  Truth weeds: {len(truth)}  (thresh {data['weed_match_m']}m)")

    start_ns = data["start_ts_ns"] or kept[0][0]

    with tempfile.TemporaryDirectory(prefix="skydock_vid_") as tmp:
        tmp_path = Path(tmp)
        lines = ["ffconcat version 1.0"]
        for j, ((ts_ns, img_path), dur) in enumerate(zip(kept, durations, strict=True)):
            frame = compose_frame(img_path, ts_ns, data, start_ns, truth)
            if frame is None:
                print(f"Error: compose failed for {img_path}")
                sys.exit(1)
            png = tmp_path / f"f_{j:06d}.png"
            if not cv2.imwrite(str(png), frame):
                print(f"Error: could not write {png}")
                sys.exit(1)
            pesc = str(png.resolve()).replace("\\", "/").replace("'", "'\\''")
            lines.append(f"file '{pesc}'")
            lines.append(f"duration {dur:.6f}")
            if (j + 1) % 50 == 0 or (j + 1) == len(kept):
                print(f"  {j + 1}/{len(kept)} frames processed")

        if len(lines) <= 1:
            print("Error: no frames written")
            sys.exit(1)

        concat_path = tmp_path / "list.ffconcat"
        concat_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        r = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_path),
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "23",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                "-an",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            timeout=7200,
        )
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "").strip()
            print(f"Error: ffmpeg failed ({r.returncode}). {err[:1200]}")
            sys.exit(1)

    print(f"Video saved (real-time H.264): {output_path}")


def main():
    ap = argparse.ArgumentParser(description="Generate mission video from JSONL + frames/")
    ap.add_argument("mission_dir", type=Path, help="Path to mission directory (e.g. rpi_missions/0006)")
    ap.add_argument(
        "--fps",
        type=float,
        default=None,
        metavar="N",
        help="Fixed output frame rate (equal time per frame). If omitted, video uses real wall-clock "
        "spacing from JPEG filename timestamps.",
    )
    ap.add_argument("--output", type=Path, default=None,
                    help="Output path (default: <mission_dir>/mission_video.mp4)")
    ap.add_argument(
        "--reencode-only",
        action="store_true",
        help="Only re-encode existing mission_video.mp4 to H.264 (no frame re-render)",
    )
    args = ap.parse_args()

    mission_dir = args.mission_dir
    if not mission_dir.is_absolute():
        # Resolve relative to repo root (two levels up from tools/)
        repo_root = Path(__file__).resolve().parent.parent
        mission_dir = repo_root / mission_dir

    if not mission_dir.exists():
        print(f"Error: mission directory not found: {mission_dir}")
        sys.exit(1)

    output_path = args.output or (mission_dir / "mission_video.mp4")
    if args.reencode_only:
        if not output_path.is_file():
            print(f"Error: no file to re-encode: {output_path}")
            sys.exit(1)
        print(f"Re-encoding to H.264: {output_path}")
        if not transcode_h264_for_web(output_path):
            sys.exit(1)
        print("Done.")
        return

    if args.fps is not None:
        build_video_fixed_fps(mission_dir, output_path, float(args.fps))
    else:
        build_video_realtime(mission_dir, output_path)


if __name__ == "__main__":
    main()
