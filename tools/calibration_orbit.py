#!/usr/bin/env python3
"""
Camera-mount calibration orbit.

Flies the drone in a horizontal circle around its CURRENT position, at the altitude it
is already holding when the script starts, with a radius you choose (hard-capped below
15 m). ArduPilot yaws toward the direction of travel, so one loop sweeps the heading
through a full 360° — exactly the geometric diversity needed to observe the camera
boresight (see tools/estimate_camera_mount.py and the Spring Valley 0063 analysis).

Every tick it logs an ``fsm_tick`` record (drone_state + the latest camera Frame) into a
fresh ``missions/NNNN/`` directory, so the resulting log feeds straight into
``estimate_camera_mount.py`` afterwards.

HOW TO USE (real flight)
------------------------
1. Take off and fly manually to sit roughly over the surveyed target, at the altitude
   you want to calibrate at (lower = more angular sensitivity; ~10 m worked well).
2. Switch the FC to GUIDED.
3. Run:  python tools/calibration_orbit.py --radii 4 8 12 --loops 2
4. To abort at any time, flip the mode switch OUT of GUIDED — the script detects the
   mode change, stops commanding, and exits, leaving you in control.

    python tools/calibration_orbit.py --radii 4 8 12 --loops 2    # real FC, 3 orbits
    python tools/calibration_orbit.py -s --radii 5 10             # SITL, 2 orbits

SAFETY: this commands a real aircraft. It only ever sends position targets within
``--radius`` of where the drone already is, never changes altitude, and never arms or
changes mode for you. It refuses to start unless the FC is already GUIDED and airborne.
"""

import argparse
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import constants
from constants import TARGET_SIM_SPEED
from telemetry import Telemetry
import telemetry as telemetry_mod
from utils import haversine_distance

RADIUS_CAP_M = 15.0          # hard upper bound the user asked for
MIN_AIRBORNE_ALT_M = 2.0     # refuse to orbit if we're basically on the ground
EARTH_M_PER_DEG = 111320.0


def offset_latlon(lat, lon, north_m, east_m):
    """Return (lat, lon) shifted by the given metres North/East."""
    dlat = north_m / EARTH_M_PER_DEG
    dlon = east_m / (EARTH_M_PER_DEG * math.cos(math.radians(lat)))
    return lat + dlat, lon + dlon


def wait_ready(drone_state, timeout=30.0):
    start = time.time()
    while time.time() - start < timeout:
        if drone_state.is_telemetry_ready and drone_state.latitude not in (0, None):
            return True
        time.sleep(0.2)
    return False


def main():
    ap = argparse.ArgumentParser(description="Fly a calibration orbit around the current position.")
    ap.add_argument("--radii", type=float, nargs="+", default=[4.0, 8.0, 12.0],
                    help=f"one or more orbit radii in metres, each < {RADIUS_CAP_M} "
                         "(flown smallest-first). Different radii sample the target at "
                         "different image positions, sharpening the boresight fit.")
    ap.add_argument("--loops", type=int, default=2, help="full revolutions per radius")
    ap.add_argument("--points", type=int, default=24, help="waypoints per revolution")
    ap.add_argument("--speed", type=float, default=1.5, help="ground speed in m/s")
    ap.add_argument("--wp-tol", type=float, default=1.5, help="arrival tolerance in metres")
    ap.add_argument("--wp-timeout", type=float, default=25.0,
                    help="give up on a waypoint after this many seconds and move on")
    ap.add_argument("-s", "--sim", action="store_true", help="connect to SITL on udp:127.0.0.1:14550")
    ap.add_argument("--connection", default=None, help="explicit MAVLink connection string")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = ap.parse_args()

    radii = sorted(args.radii)  # smallest-first: gentlest manoeuvre near the target first
    for r in radii:
        if not (0 < r < RADIUS_CAP_M):
            ap.error(f"every --radii value must be > 0 and < {RADIUS_CAP_M} m (got {r})")
    if args.loops < 1 or args.points < 4:
        ap.error("--loops >= 1 and --points >= 4")

    conn = args.connection or ("udp:127.0.0.1:14550" if args.sim else None)
    print(f"Connecting to FC ({conn or 'serial autodetect'}) ...")
    telemetry_mod.telemetry_singleton = Telemetry(connection_string=conn)
    tel = telemetry_mod.telemetry_singleton
    ds = tel.drone_state

    if not wait_ready(ds):
        sys.exit("Telemetry never became ready (no GPS fix?). Aborting.")

    # --- record the run so estimate_camera_mount.py can read it afterwards ---
    from mission_logging import (allocate_mission_dir, configure_mission_dir,
                                 init_mission_log, log_event)
    mission_dir = allocate_mission_dir(Path(__file__).resolve().parents[1])
    configure_mission_dir(mission_dir)
    init_mission_log(is_sim=args.sim)
    print(f"Logging to {mission_dir}/mission.jsonl")

    # Start the camera pipeline so frames/detections are available to log.
    try:
        from ai_class import ai_storage_singleton
        ai_storage_singleton.start_sim_ai(None)
    except Exception as e:
        print(f"WARNING: camera pipeline not started ({e}); orbit will fly but log no detections.")
        ai_storage_singleton = None

    # --- capture the centre and altitude AT START (the request: alt = whatever it's at) ---
    center_lat = ds.latitude
    center_lon = ds.longitude
    alt = ds.altitude_rel_home
    mode = tel.get_mode()

    print("\n=== Calibration orbit plan ===")
    print(f"  centre      : {center_lat:.7f}, {center_lon:.7f}")
    print(f"  altitude    : {alt:.1f} m (held constant)")
    print(f"  radii       : {', '.join(f'{r:.1f}' for r in radii)} m")
    print(f"  loops/points: {args.loops} x {args.points} per radius "
          f"({len(radii) * args.loops * args.points} waypoints total)")
    print(f"  speed       : {args.speed:.1f} m/s")
    print(f"  FC mode     : {mode}")

    if mode != "GUIDED":
        sys.exit("FC is not in GUIDED — switch to GUIDED and re-run. (Refusing to set mode for you.)")
    if alt is None or alt < MIN_AIRBORNE_ALT_M:
        sys.exit(f"Altitude {alt} m is below {MIN_AIRBORNE_ALT_M} m — take off first. Aborting.")

    if not args.yes:
        resp = input("\nProceed with the orbit? Flip out of GUIDED any time to abort. [y/N] ").strip().lower()
        if resp != "y":
            sys.exit("Cancelled.")

    def aborted():
        """True if the pilot took manual control (left GUIDED)."""
        if tel.get_mode() != "GUIDED":
            print("\nMode left GUIDED — pilot has control. Stopping orbit.")
            return True
        return False

    def log_tick():
        frame = ai_storage_singleton.get_latest_frame() if ai_storage_singleton else None
        log_event("fsm_tick", logger="calibration_orbit", level="DEBUG",
                  drone_state=ds, frame=frame, state="CALIBRATION_ORBIT")

    # --- fly each circle, smallest radius first ---
    wps_per_orbit = args.loops * args.points
    try:
        for radius in radii:
            if aborted():
                break
            print(f"\n-- orbit at {radius:.1f} m --")
            for i in range(wps_per_orbit):
                if aborted():
                    raise KeyboardInterrupt
                theta = 2 * math.pi * (i % args.points) / args.points
                north = radius * math.cos(theta)
                east = radius * math.sin(theta)
                wp_lat, wp_lon = offset_latlon(center_lat, center_lon, north, east)

                tel.fly_to_point(wp_lat, wp_lon, alt, speed_ms=args.speed)
                print(f"  r{radius:.0f} wp {i + 1:3d}/{wps_per_orbit}  "
                      f"bearing {math.degrees(theta):3.0f}°", end="  ")

                t0 = time.time()
                while True:
                    if aborted():
                        raise KeyboardInterrupt
                    dist = haversine_distance(ds.latitude, ds.longitude, wp_lat, wp_lon)
                    log_tick()
                    if dist <= args.wp_tol:
                        print(f"reached ({dist:.1f} m)")
                        break
                    if time.time() - t0 > args.wp_timeout:
                        print(f"timeout ({dist:.1f} m) — moving on")
                        break
                    time.sleep(0.2 / TARGET_SIM_SPEED)
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        # Settle back over the centre and hold; never touch mode/arming.
        if tel.get_mode() == "GUIDED":
            print("Returning to centre and holding (still GUIDED).")
            tel.fly_to_point(center_lat, center_lon, alt, speed_ms=args.speed)

    print(f"\nDone. Analyse with:\n  python tools/estimate_camera_mount.py {mission_dir} "
          f"--objective consistency   # one orbit target -> truth-free single-cluster fit")


if __name__ == "__main__":
    main()
