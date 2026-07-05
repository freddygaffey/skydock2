#!/usr/bin/env bash
# CAMERA-MOUNT CALIBRATION ORBIT — launch-day crib sheet (July 2026)
#
# Why: May-era logs show the pixel->body mapping is NOT identity — best fit is
# image-right = body-BACKWARD, image-down = body-RIGHT (mirrored 90 deg).
# This flight confirms/refutes that for the CURRENT 640x640 camera config.
# Full background: docs/Bug Notes.md ("camera-orientation re-check").
#
# ON THE DAY:
#   1. Put ONE ball on a surveyed/marked spot.
#   2. Take off manually, hover roughly over the ball at ~10 m.
#   3. Switch the FC to GUIDED.
#   4. Run this script (on the Pi, from the repo root):
#        ./RUN_CALIBRATION_ORBIT.sh
#   5. Abort anytime by flipping the mode switch OUT of GUIDED.
#
# AFTERWARDS (analysis, on any machine with the mission log):
#   python tools/estimate_camera_mount.py missions/<NNNN> --objective consistency
#
# The orbit holds altitude, caps radius at 15 m, never arms and never changes
# mode for you. See tools/calibration_orbit.py for all flags.

cd "$(dirname "$0")"
exec python tools/calibration_orbit.py --radii 4 8 12 --loops 2 "$@"
