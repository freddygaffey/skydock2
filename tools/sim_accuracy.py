import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


def iter_events(path: Path) -> Iterable[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@dataclass
class Point:
    lat: float
    lon: float


def load_truth(sim_json: Path) -> list[Point]:
    data = json.loads(sim_json.read_text(encoding="utf-8"))
    return [Point(lat=float(lat), lon=float(lon)) for lat, lon in data["weed_locations"]]


def load_predictions(mission_jsonl: Path) -> list[Point]:
    preds: list[Point] = []
    for ev in iter_events(mission_jsonl):
        if ev.get("event") != "weed_detected":
            continue
        lat = ev.get("lat")
        lon = ev.get("lon")
        if lat is None or lon is None:
            continue
        preds.append(Point(lat=float(lat), lon=float(lon)))
    return preds


def match(preds: list[Point], truth: list[Point], thresh_m: float) -> tuple[int, int, int]:
    used_truth = set()
    tp = 0
    fp = 0
    for p in preds:
        best_idx = None
        best_d = float("inf")
        for i, t in enumerate(truth):
            if i in used_truth:
                continue
            d = haversine_m(p.lat, p.lon, t.lat, t.lon)
            if d < best_d:
                best_d = d
                best_idx = i
        if best_idx is not None and best_d <= thresh_m:
            tp += 1
            used_truth.add(best_idx)
        else:
            fp += 1
    fn = len(truth) - len(used_truth)
    return tp, fp, fn


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mission_jsonl", type=Path, help="Path to missions/XXXX/mission.jsonl")
    ap.add_argument("--truth", required=True, type=Path, help="Path to sim_data/<file>.json")
    ap.add_argument("--thresh-m", type=float, default=0.5, help="Match threshold in meters")
    args = ap.parse_args()

    truth = load_truth(args.truth)
    preds = load_predictions(args.mission_jsonl)

    tp, fp, fn = match(preds, truth, float(args.thresh_m))
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0

    print(f"truth={len(truth)} preds={len(preds)} thresh_m={args.thresh_m}")
    print(f"TP={tp} FP={fp} FN={fn}")
    print(f"precision={prec:.3f} recall={rec:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

