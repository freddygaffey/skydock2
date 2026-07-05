#!/usr/bin/env python3
"""Verify the camera pixel->body orientation from PIXEL MOTION in a mission log.

Truth-free (no surveyed target needed): works on ANY flight with saved frames.

Method (Fred's, July 2026):
  1. Phase-correlate consecutive saved frames -> scene translation per pair.
     While the drone flies forward, the scene streams opposite its motion; the
     image axis and sign of that flow reveal where body-forward lands in the image.
  2. Track sparse features through the yaw turns -> image rotation sign.
     Compass heading says which way the drone turned; a mirrored image rotates
     the SAME sense as the compass, a proper (unmirrored) one the OPPOSITE sense.
  3. Match both signatures against the 8 candidate mappings (4 rotations x mirror).

Clock offset between frame filenames and telemetry is self-calibrated by
correlating |image rotation| against |compass yaw rate|.

Result on logs/0063 (May 2026, 1280x1280 pipeline): mirror90 —
image-right = body-BACKWARD, image-down = body-RIGHT (image horizontally
mirrored + 90 deg mount). Run this on the first flight of any new camera
config before trusting utils.detection_to_ned.

Usage:
    python tools/camera_orientation_from_flow.py logs/0063
    python tools/camera_orientation_from_flow.py missions/0142 --fov-x 55.3 --fov-y 31.2
"""

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def Rz(a):
    return np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])


SWAP = np.array([[0.0, 1, 0], [1, 0, 0], [0, 0, 1]])
CANDIDATES = {
    "identity  (img-right=fwd)": np.eye(3),
    "Rz90": Rz(math.pi / 2),
    "Rz180": Rz(math.pi),
    "Rz270": Rz(3 * math.pi / 2),
    "mirror0   (swap)": SWAP,
    "mirror90  (img-right=BACK, img-down=RIGHT)": Rz(math.pi / 2) @ SWAP,
    "mirror180": Rz(math.pi) @ SWAP,
    "mirror270": Rz(3 * math.pi / 2) @ SWAP,
}


def signature(R, fx, fy):
    """(flow_u_per_fwd, flow_v_per_fwd, handedness) predicted for a mapping.

    flow_* : scene pixel motion per +1 m/s body-forward at 10 m altitude.
    handedness : +1 if the scene rotates the SAME sense as a compass (CW) yaw,
                 -1 if opposite (i.e. -1 = proper rotation, +1 = mirrored).
    """
    P = np.zeros(3)
    pos = np.array([0.0, 0.0, -10.0])

    def pix(P_ned, pos_ned, yaw):
        cam = R.T @ (Rz(yaw).T @ (P_ned - pos_ned))
        return np.array([fx * cam[0] / cam[2], fy * cam[1] / cam[2]])

    base = pix(P, pos, 0.0)
    flow = (pix(P, pos + np.array([0.1, 0, 0]), 0.0) - base) * 10
    # handedness from an off-nadir ring point under a small +CW yaw
    Q = np.array([3.0, 1.0, 0.0])
    a0, a1 = pix(Q, pos, 0.0), pix(Q, pos, 0.05)
    d = math.atan2(a1[1] * fx / fy, a1[0]) - math.atan2(a0[1] * fx / fy, a0[0])
    d = (d + math.pi) % (2 * math.pi) - math.pi
    return flow[0], flow[1], (1 if d > 0 else -1)


def load_telemetry(jsonl):
    T, HD, VX, VY, ALT = [], [], [], [], []
    for line in open(jsonl):
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("event") != "telemetry_sample":
            continue
        ds = e["drone_state"]
        if ds.get("heading") is None or ds.get("latitude") is None:
            continue
        T.append(datetime.fromisoformat(e["ts"].replace("Z", "+00:00")).timestamp())
        HD.append(ds["heading"])
        VX.append(ds.get("velocity_x") or 0.0)
        VY.append(ds.get("velocity_y") or 0.0)
        ALT.append(ds.get("altitude_rel_home") or 0.0)
    T = np.array(T)
    return T - T[0], np.array(HD), np.array(VX), np.array(VY), np.array(ALT)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mission", help="mission dir containing mission.jsonl and frames/")
    ap.add_argument("--fov-x", type=float, default=55.3)
    ap.add_argument("--fov-y", type=float, default=31.2)
    ap.add_argument("--min-rate", type=float, default=15.0,
                    help="deg/s of compass yaw a moment needs to count for the rotation test")
    args = ap.parse_args()
    mdir = Path(args.mission)

    files = sorted((mdir / "frames").glob("[0-9]*.jpg"), key=lambda p: int(p.stem))
    if len(files) < 50:
        sys.exit(f"only {len(files)} frames in {mdir}/frames — need a real flight log")
    first = cv2.imread(str(files[0]), cv2.IMREAD_GRAYSCALE)
    Hpx, Wpx = first.shape[:2]
    fx = Wpx / (2 * math.tan(math.radians(args.fov_x / 2)))
    fy = Hpx / (2 * math.tan(math.radians(args.fov_y / 2)))
    print(f"{len(files)} frames at {Wpx}x{Hpx}; fx={fx:.0f} fy={fy:.0f} px")

    tt, hd, vx, vy, alt = load_telemetry(mdir / "mission.jsonl")
    yawrate = np.degrees(np.gradient(np.unwrap(np.radians(hd)), tt))
    ts = np.array([int(p.stem) for p in files])
    tr = (ts - ts[0]) / 1e9

    # --- per-pair translation (phase correlation) and rotation (LK + affine) ---
    DW = 320
    AW, AH = 512, max(64, int(512 * fx / fy))  # aspect-corrected for rigid rotation
    han = cv2.createHanningWindow((DW, DW), cv2.CV_32F)
    trans, rot = [], []  # (t_rel, u_px_s, v_px_s) / (t_rel, deg_s)
    g_prev = None
    for i, f in enumerate(files):
        g = cv2.imread(str(f), cv2.IMREAD_GRAYSCALE)
        small = cv2.resize(g, (DW, DW)).astype(np.float32)
        angp = cv2.resize(g, (AW, AH))
        if g_prev is not None:
            dt = tr[i] - tr[i - 1]
            if 0.02 < dt < 0.2:
                (du, dv), resp = cv2.phaseCorrelate(g_prev[0], small, han)
                if resp > 0.05:
                    trans.append((tr[i], du * Wpx / DW / dt, dv * Hpx / DW / dt))
                p0 = cv2.goodFeaturesToTrack(g_prev[1], 300, 0.01, 8)
                if p0 is not None and len(p0) >= 50:
                    p1, st, _ = cv2.calcOpticalFlowPyrLK(g_prev[1], angp, p0, None,
                                                         winSize=(31, 31), maxLevel=4)
                    m = st.ravel() == 1
                    if m.sum() >= 50:
                        M, _ = cv2.estimateAffinePartial2D(p0[m], p1[m], ransacReprojThreshold=2.0)
                        if M is not None:
                            rot.append((tr[i], math.degrees(math.atan2(M[1, 0], M[0, 0])) / dt))
        g_prev = (small, angp)
    trans, rot = np.array(trans), np.array(rot)
    print(f"flow pairs: {len(trans)}, rotation pairs: {len(rot)}")

    # --- clock offset: |image rotation| vs |compass yaw rate| ---
    best = (0.0, -2.0)
    for off in np.arange(-180, 180, 0.5):
        yr = np.interp(rot[:, 0] + off, tt, np.abs(yawrate), left=np.nan, right=np.nan)
        m = ~np.isnan(yr)
        if m.sum() < 300:
            continue
        c = np.corrcoef(np.abs(rot[m, 1]), yr[m])[0, 1]
        if c > best[1]:
            best = (off, c)
    OFF, corr = best
    print(f"clock offset: frame_time {OFF:+.1f} s = telemetry time (corr {corr:.2f})")
    if corr < 0.5:
        print("WARNING: poor clock alignment — results may be unreliable")

    # --- measured signature 1: forward-flight flow ---
    us, vs = [], []
    for t, u, v in trans:
        i = min(max(np.searchsorted(tt, t + OFF), 0), len(tt) - 1)
        sp = math.hypot(vx[i], vy[i])
        if sp < 0.5 or alt[i] < 4 or abs(yawrate[i]) > 10:
            continue
        yaw = math.radians(hd[i])
        fwd = math.cos(yaw) * vx[i] + math.sin(yaw) * vy[i]
        if abs(fwd) < 0.8 * sp:
            continue
        us.append(u / fwd * alt[i] / 10)   # px/s per m/s, normalised to 10 m
        vs.append(v / fwd * alt[i] / 10)
    mu, mv = np.median(us), np.median(vs)
    print(f"\nforward-flight flow (n={len(us)}): u {mu:+.0f} px/s, v {mv:+.0f} px/s per m/s at 10 m")

    # --- measured signature 2: rotation handedness ---
    yr = np.interp(rot[:, 0] + OFF, tt, yawrate)
    m = (np.abs(yr) > args.min_rate) & (np.abs(rot[:, 1]) > 10)
    hand = np.sign(np.median(np.sign(rot[m, 1]) * np.sign(yr[m]))) if m.sum() >= 20 else 0
    agree = (np.sign(rot[m, 1]) == np.sign(yr[m])).mean() * 100 if m.sum() else float("nan")
    print(f"rotation handedness (n={m.sum()}): image turns "
          f"{'SAME' if hand > 0 else 'OPPOSITE' if hand < 0 else 'UNDETERMINED'} sense as compass "
          f"({agree:.0f}% agreement) -> {'MIRRORED' if hand > 0 else 'proper' if hand < 0 else '?'}")

    # --- verdict ---
    print("\ncandidate signatures (u/fwd, v/fwd, handedness) vs measured "
          f"({mu:+.0f}, {mv:+.0f}, {'+1' if hand > 0 else '-1'}):")
    scored = []
    for name, R in CANDIDATES.items():
        su, sv, sh = signature(R, fx, fy)
        d = math.hypot(su - mu, sv - mv) + (0 if sh == hand else 1000)
        scored.append((d, name, su, sv, sh))
        print(f"  {name:44s} ({su:+4.0f}, {sv:+4.0f}, {sh:+d})   score {d:6.0f}")
    scored.sort()
    print(f"\n>>> VERDICT: {scored[0][1]}")
    if scored[0][0] > 200:
        print("    (weak match — inspect the numbers above before trusting it)")


if __name__ == "__main__":
    main()
