#!/usr/bin/env python3
"""
Estimate the camera-to-body mounting rotation from real flight logs.

utils.detection_to_ned() currently assumes R_cam_to_body = identity (camera perfectly
nadir, frame axes aligned to body N/E/down). This tool checks that assumption against
real data: it back-projects every logged detection to the ground and fits the 3-angle
mounting offset (roll/pitch/yaw) that best lines detections up with the known weed
GPS locations.

Confound it co-estimates: GPS and attitude are on different clocks, so a fixed time
lag dead-reckons into an apparent mount offset. We optimise (roll, pitch, yaw, gps_lag)
jointly; reporting the mount angles without the lag would be meaningless.

Ground truth is each log's own mission_plan weed_locations (self-contained), so logs
from the same site can be pooled. Detections are robustly matched to the nearest truth
weed; a pre-filter at identity throws out false positives (grass) that would otherwise
swamp the fit. The objective is the MEDIAN nearest-truth error (robust to the FPs that
survive the filter).

Usage:
    python tools/estimate_camera_mount.py logs/0218 logs/0235 logs/0249
    python tools/estimate_camera_mount.py logs/0218 --prefilter 12 --fov-x 55.3 --fov-y 31.2
"""

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils import haversine_distance


def Rx(a):
    return np.array([[1, 0, 0], [0, np.cos(a), -np.sin(a)], [0, np.sin(a), np.cos(a)]])


def Ry(a):
    return np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])


def Rz(a):
    return np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])


def load_samples(mission_dir):
    """Return (list of (sample_dict), truth_weeds). sample = dict with px,py,roll,pitch,
    yaw,lat,lon,alt,vx,vy."""
    p = Path(mission_dir)
    jsonl = p / "mission.jsonl" if p.is_dir() else p
    truth = None
    samples = []
    for line in open(jsonl):
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("event") == "mission_plan":
            truth = e["mission"].get("weed_locations")
        ds = e.get("drone_state")
        frame = e.get("frame") or {}
        dets = frame.get("detections") or []
        if not ds or not dets:
            continue
        rot = ds.get("rotation") or ds.get("rotaion") or {}
        if ds.get("latitude") is None:
            continue
        for d in dets:
            bbox = d.get("bbox")
            if not (bbox and len(bbox) == 2):
                continue
            samples.append({
                "px": (bbox[0][0] + bbox[1][0]) / 2,
                "py": (bbox[0][1] + bbox[1][1]) / 2,
                "roll": float(rot.get("x", 0) or 0),
                "pitch": float(rot.get("y", 0) or 0),
                "yaw": float(rot.get("z", 0) or 0),
                "lat": float(ds["latitude"]),
                "lon": float(ds["longitude"]),
                "alt": float(ds.get("altitude_rel_home") or 0),
                "vx": float(ds.get("velocity_x") or 0),
                "vy": float(ds.get("velocity_y") or 0),
            })
    return samples, truth


def project(s, R_mount, lag, intr):
    fx, fy, cx, cy = intr
    x_cam = (s["px"] - cx) / fx
    y_cam = (s["py"] - cy) / fy
    cam_ray = np.array([x_cam, y_cam, 1.0])
    cam_ray /= np.linalg.norm(cam_ray)
    ray_body = R_mount @ cam_ray
    R_body_to_ned = Rz(s["yaw"]) @ Ry(s["pitch"]) @ Rx(s["roll"])
    ray_ned = R_body_to_ned @ ray_body
    if ray_ned[2] < 0.3:
        return None
    factor = s["alt"] / ray_ned[2]
    N = factor * ray_ned[0]
    E = factor * ray_ned[1]
    # dead-reckon the drone position forward by the GPS lag
    lat = s["lat"] + (s["vy"] * 0 + s["vx"] * lag) / 111320 + N / 111320
    lon = s["lon"] + (s["vy"] * lag) / (111320 * math.cos(math.radians(s["lat"]))) \
        + E / (111320 * math.cos(math.radians(s["lat"])))
    return lat, lon


def nearest(lat, lon, truth):
    return min(haversine_distance(lat, lon, w["lat"], w["lon"]) for w in truth)


def errors_for(params, samples_by_truth, intr):
    roll, pitch, yaw, lag = params
    R_mount = Rz(yaw) @ Ry(pitch) @ Rx(roll)
    errs = []
    for samples, truth, _m in samples_by_truth:
        for s in samples:
            pr = project(s, R_mount, lag, intr)
            if pr is None:
                continue
            errs.append(nearest(pr[0], pr[1], truth))
    return np.array(errs)


def objective(params, samples_by_truth, intr):
    errs = errors_for(params, samples_by_truth, intr)
    if len(errs) == 0:
        return 1e6
    return float(np.median(errs))  # robust to surviving false positives


def consistency_objective(params, filtered, intr):
    """Truth-free: a stationary weed must back-project to ONE point. Minimise the median
    spread of each field's projections about their own centroid. Needs no accurate truth;
    lawnmower heading reversals make the mount + lag observable."""
    roll, pitch, yaw, lag = params
    R_mount = Rz(yaw) @ Ry(pitch) @ Rx(roll)
    spreads = []
    for samples, _truth, _m in filtered:
        pts = [project(s, R_mount, lag, intr) for s in samples]
        pts = [p for p in pts if p is not None]
        if len(pts) < 3:
            continue
        clat = np.median([p[0] for p in pts])
        clon = np.median([p[1] for p in pts])
        for p in pts:
            spreads.append(haversine_distance(p[0], p[1], clat, clon))
    if not spreads:
        return 1e6
    return float(np.median(spreads))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("missions", nargs="+", help="mission dirs/files (pool logs sharing a site)")
    ap.add_argument("--fov-x", type=float, default=55.3, help="horizontal FOV deg (real cam 55.3)")
    ap.add_argument("--fov-y", type=float, default=31.2, help="vertical FOV deg (real cam 31.2)")
    ap.add_argument("--prefilter", type=float, default=15.0,
                    help="keep detections landing within this many m of a weed at identity")
    ap.add_argument("--objective", choices=["truth", "consistency"], default="consistency",
                    help="'consistency' (default) fits the tightest single-point cluster per "
                         "field — truth-free, robust to inaccurate truth weeds. 'truth' fits "
                         "nearest-weed error (needs accurate truth).")
    args = ap.parse_args()
    obj = consistency_objective if args.objective == "consistency" else objective

    # intrinsics from the real lores stream (640x640)
    W = H = 640
    fx = W / (2 * np.tan(np.radians(args.fov_x / 2)))
    fy = H / (2 * np.tan(np.radians(args.fov_y / 2)))
    intr = (fx, fy, W / 2, H / 2)

    samples_by_truth = []
    total = 0
    for m in args.missions:
        samples, truth = load_samples(m)
        if not truth:
            print(f"  {m}: no truth weeds, skipped", file=sys.stderr)
            continue
        total += len(samples)
        samples_by_truth.append((samples, truth, m))
    print(f"Loaded {total} raw detections from {len(samples_by_truth)} logs")

    # Pre-filter false positives at identity mount, zero lag.
    R_id = np.eye(3)
    filtered = []
    for samples, truth, m in samples_by_truth:
        keep = []
        for s in samples:
            pr = project(s, R_id, 0.0, intr)
            if pr and nearest(pr[0], pr[1], truth) <= args.prefilter:
                keep.append(s)
        print(f"  {m}: {len(keep)}/{len(samples)} detections within {args.prefilter} m at identity")
        if keep:
            filtered.append((keep, truth, m))
    if not filtered:
        sys.exit("No detections survived the pre-filter — loosen --prefilter or check FOV.")

    base = obj([0, 0, 0, 0], filtered, intr)
    n_used = sum(len(s) for s, _, _ in filtered)
    metric = "cluster spread" if args.objective == "consistency" else "median error"
    print(f"\nBaseline (identity mount, 0 lag): {metric} {base:.2f} m over {n_used} dets")

    # Coarse grid seed then Nelder-Mead refine (objective is non-smooth / multimodal in yaw).
    best = None
    for yaw0 in np.radians(np.arange(-30, 31, 10)):
        for lag0 in (0.0, 0.3, 0.6):
            res = minimize(obj, [0.0, 0.0, yaw0, lag0],
                           args=(filtered, intr), method="Nelder-Mead",
                           options={"xatol": 1e-4, "fatol": 1e-4, "maxiter": 2000})
            if best is None or res.fun < best.fun:
                best = res

    roll, pitch, yaw, lag = best.x
    print("\n=== Best-fit camera mount (R_cam_to_body = Rz(yaw)·Ry(pitch)·Rx(roll)) ===")
    print(f"  roll  offset : {math.degrees(roll):+7.2f} deg")
    print(f"  pitch offset : {math.degrees(pitch):+7.2f} deg")
    print(f"  yaw   offset : {math.degrees(yaw):+7.2f} deg")
    print(f"  gps lag      : {lag:+.3f} s  (co-estimated; aliases into mount if ignored)")
    print(f"  {metric:<12} : {best.fun:.2f} m   (was {base:.2f} m at identity)")

    # Show how tight each field's cluster became and how far its centroid sits from the
    # (rough, possibly inaccurate) truth weed — the latter is a read on the truth, not the fit.
    R_mount = Rz(yaw) @ Ry(pitch) @ Rx(roll)
    print("\nPer-field: cluster tightness, and centroid offset from rough truth")
    for samples, truth, m in filtered:
        pts = [project(s, R_mount, lag, intr) for s in samples]
        pts = [p for p in pts if p is not None]
        if len(pts) < 3:
            continue
        clat = float(np.median([p[0] for p in pts]))
        clon = float(np.median([p[1] for p in pts]))
        spread = float(np.median([haversine_distance(p[0], p[1], clat, clon) for p in pts]))
        to_truth = nearest(clat, clon, truth)
        print(f"  {m}: n={len(pts):4d}  spread(med)={spread:5.2f} m  "
              f"centroid->truth={to_truth:5.2f} m")


if __name__ == "__main__":
    main()
