"""Tests for mission_gen.py — lawnmower scan-path generation and save_mission.

Run with:  python -m pytest tests/test_mission_gen.py
"""

import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mission_gen import generate_scan_path, save_mission  # noqa: E402

M_PER_DEG_LAT = 111_111.0


def weeds(*coords):
    return [{"id": i, "lat": lat, "lon": lon} for i, (lat, lon) in enumerate(coords)]


def test_path_brackets_all_weeds_with_padding():
    w = weeds((-35.3632, 149.1652), (-35.3635, 149.1660), (-35.3630, 149.1648))
    padding_m = 5
    path = generate_scan_path(w, row_spacing_m=8, padding_m=padding_m)

    lats = [p[0] for p in path]
    lons = [p[1] for p in path]
    weed_lats = [d["lat"] for d in w]
    weed_lons = [d["lon"] for d in w]

    pad_lat = padding_m / M_PER_DEG_LAT
    # The first row starts a full pad below the southernmost weed.
    assert min(lats) == pytest.approx(min(weed_lats) - pad_lat)
    # Rows are stepped, so the top row lands at or above the northernmost weed
    # (the final partial row up to the padded edge is not swept — lawnmower behaviour).
    assert max(lats) >= max(weed_lats)
    # The longitude band (padded) brackets every weed.
    assert min(lons) <= min(weed_lons)
    assert max(lons) >= max(weed_lons)


def test_waypoints_are_lat_lon_pairs():
    path = generate_scan_path(weeds((-35.3632, 149.1652), (-35.3635, 149.1660)))
    for pt in path:
        assert len(pt) == 2
        lat, lon = pt
        assert -90 <= lat <= 90
        assert -180 <= lon <= 180


def test_rows_spaced_by_row_spacing():
    w = weeds((-35.3600, 149.1650), (-35.3650, 149.1650))  # ~555 m N-S span
    row_spacing_m = 8
    path = generate_scan_path(w, row_spacing_m=row_spacing_m, padding_m=5)

    # Distinct row latitudes, in order.
    row_lats = sorted(set(p[0] for p in path))
    diffs = [(b - a) * M_PER_DEG_LAT for a, b in zip(row_lats, row_lats[1:])]
    for d in diffs:
        assert d == pytest.approx(row_spacing_m, abs=0.5)


def test_serpentine_alternation():
    w = weeds((-35.3600, 149.1650), (-35.3650, 149.1660))
    path = generate_scan_path(w, row_spacing_m=8, padding_m=5)
    # Path is pairs [a, b] per row; consecutive rows reverse direction, so the
    # end of one row and the start of the next share a longitude.
    for i in range(0, len(path) - 2, 2):
        assert path[i + 1][1] == pytest.approx(path[i + 2][1])


def test_single_weed_produces_valid_box():
    path = generate_scan_path(weeds((-35.3632, 149.1652)), row_spacing_m=8, padding_m=5)
    assert len(path) >= 2
    lats = [p[0] for p in path]
    assert max(lats) > min(lats)  # padding gives the box height


def test_save_mission_roundtrip(tmp_path):
    w = weeds((-35.3632, 149.1652), (-35.3635, 149.1660))
    out = save_mission(w, name="unit_test_mission", out_dir=str(tmp_path))

    assert Path(out).exists()
    data = json.loads(Path(out).read_text())
    assert data["weed_locations"] == w
    assert len(data["scan_path"]) >= 2
    # field_center is the centroid of the weeds.
    assert data["field_center"][0] == pytest.approx(sum(d["lat"] for d in w) / len(w))
    assert data["field_center"][1] == pytest.approx(sum(d["lon"] for d in w) / len(w))
