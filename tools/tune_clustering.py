"""Offline sweep of the weed-clustering constants over a recorded flight.

Re-runs the EXACT production clustering (states.scan.cluster_latlon_points)
on a flight's stored detections for every candidate (MIN_WEED_SPACING,
MIN_NUM_DET) pair and scores each against ground truth — no re-flying.

Truth is a JSON file with weed_locations (sim_data/*.json or a
real_missions/*.json marked with RTK GPS — often cm-precision; a few real
flights may have inaccurate truth, so judge per-flight tables individually
before trusting an aggregate).

Usage:
  python tools/tune_clustering.py missions/0139 --truth sim_data/0010.json
  python tools/tune_clustering.py <flight_dir> --truth real_missions/redhill.json \
      --frame-size 640         # real flights: detections are in 640x640 pixels

  --spacing 0.5,1,1.5,2,3,4    candidate MIN_WEED_SPACING values (metres)
  --min-det 1,2,3,4,5,6        candidate MIN_NUM_DET values
  --thresh-m 2.0               truth-match radius for scoring (same as sim_accuracy)
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("flight_dir", type=Path,
                    help="mission/flight dir containing droneDB.db")
    ap.add_argument("--truth", type=Path, required=True,
                    help="JSON with weed_locations (sim_data or real_missions format)")
    ap.add_argument("--thresh-m", type=float, default=2.0)
    ap.add_argument("--spacing", default="0.5,1,1.5,2,3,4",
                    help="comma-separated MIN_WEED_SPACING candidates (m)")
    ap.add_argument("--min-det", default="1,2,3,4,5,6",
                    help="comma-separated MIN_NUM_DET candidates")
    ap.add_argument("--frame-size", type=int, default=None,
                    help="override drone_state width/height for projection "
                         "(real flights store 640x640 detections; DB snapshots "
                         "reconstruct with the 1280 default)")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    db_file = args.flight_dir / "droneDB.db"
    if not db_file.exists():
        print(f"error: {db_file} not found", file=sys.stderr)
        return 2

    # Import order matters: DB path must be set before DB_abstraction imports DB.
    import DB
    DB.set_db_path(str(db_file))
    from DB_abstraction import db_abstraction
    from states.scan import cluster_latlon_points
    from utils import detection_to_latlon
    import constants
    from sim_accuracy import Point, load_truth, match, haversine_m

    truth = load_truth(args.truth)
    snapshots = db_abstraction.get_all_snapshots()

    det_locs: list[tuple[float, float]] = []
    for snap in snapshots:
        ds = snap.drone_state
        if args.frame_size:
            ds.width = args.frame_size
            ds.height = args.frame_size
        for det in snap.frame.detection:
            loc = detection_to_latlon(ds, det)
            if math.isfinite(loc[0]) and math.isfinite(loc[1]):
                det_locs.append(loc)

    print(f"flight: {args.flight_dir}  truth: {args.truth} ({len(truth)} weeds)")
    print(f"snapshots: {len(snapshots)}  projected detections: {len(det_locs)}")
    if not det_locs:
        print("error: no usable detections in this flight", file=sys.stderr)
        return 2

    spacings = [float(s) for s in args.spacing.split(",")]
    min_dets = [int(s) for s in args.min_det.split(",")]
    current = (float(constants.MIN_WEED_SPACING), int(constants.MIN_NUM_DET))

    print(f"\n{'spacing':>8} {'min_det':>8} {'clusters':>9} {'TP':>4} {'FP':>4} "
          f"{'FN':>4} {'mean_err_m':>11}")
    for spacing in spacings:
        for min_det in min_dets:
            clusters = cluster_latlon_points(det_locs, spacing, min_det)
            preds = [Point(lat=c.location[0], lon=c.location[1]) for c in clusters]
            tp, fp, fn = match(preds, truth, args.thresh_m)

            errs = []
            for p in preds:
                best = min((haversine_m(p.lat, p.lon, t.lat, t.lon) for t in truth),
                           default=float("inf"))
                if best <= args.thresh_m:
                    errs.append(best)
            mean_err = sum(errs) / len(errs) if errs else float("nan")

            marker = "  <- current" if (spacing, min_det) == current else ""
            print(f"{spacing:>8.2f} {min_det:>8d} {len(preds):>9d} {tp:>4d} {fp:>4d} "
                  f"{fn:>4d} {mean_err:>11.2f}{marker}")

    # Diagnostic: detections-per-cluster histogram at the finest spacing —
    # true weeds and false positives usually separate cleanly here, and the
    # valley between them is where MIN_NUM_DET belongs.
    finest = cluster_latlon_points(det_locs, min(spacings), 1)
    sizes = sorted(len(c.det_location) for c in finest)
    print(f"\ncluster sizes at spacing={min(spacings)}m, min_det=1: {sizes}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
