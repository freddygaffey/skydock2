"""Time and geo helpers for log analysis."""

from __future__ import annotations

import math
from datetime import datetime


def parse_ts(ts_str: str) -> float:
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        return 0.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def grid_dedup(pts: list, thresh_m: float = 0.5) -> list:
    """O(n) grid-based spatial deduplication. Returns one representative per cell."""
    cell_deg = thresh_m / 111_320.0
    seen: dict = {}
    for pt in pts:
        key = (round(pt["lat"] / cell_deg), round(pt["lon"] / cell_deg))
        if key not in seen:
            seen[key] = pt
    return list(seen.values())
