"""Tests for states.scan.cluster_latlon_points (the extracted clustering core).

Uses small lat/lon offsets around a fixed origin; 1e-5 deg latitude ~= 1.11 m.

Run with:  python -m pytest tests/test_cluster_latlon.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from states.scan import cluster_latlon_points  # noqa: E402

LAT0, LON0 = -35.363261, 149.165230
M = 1 / 111_320  # ~degrees latitude per metre


def pt(north_m: float, east_m: float = 0.0):
    return (LAT0 + north_m * M, LON0 + east_m * M)


def test_points_within_spacing_merge_into_one_cluster():
    pts = [pt(0), pt(0.5), pt(1.0)]
    clusters = cluster_latlon_points(pts, min_spacing_m=2.0, min_num_det=1)
    assert len(clusters) == 1
    assert len(clusters[0].det_location) == 3


def test_points_beyond_spacing_stay_separate():
    pts = [pt(0), pt(0), pt(10), pt(10)]
    clusters = cluster_latlon_points(pts, min_spacing_m=2.0, min_num_det=1)
    assert len(clusters) == 2


def test_min_num_det_filters_small_clusters():
    pts = [pt(0), pt(0), pt(0), pt(50)]  # 3-det cluster + a singleton
    clusters = cluster_latlon_points(pts, min_spacing_m=2.0, min_num_det=3)
    assert len(clusters) == 1
    assert len(clusters[0].det_location) == 3


def test_centroid_is_running_average():
    pts = [pt(0), pt(1.0)]
    clusters = cluster_latlon_points(pts, min_spacing_m=5.0, min_num_det=1)
    assert len(clusters) == 1
    lat, lon = clusters[0].location
    assert abs(lat - (LAT0 + 0.5 * M)) < 1e-9
    assert abs(lon - LON0) < 1e-9


def test_empty_input_gives_no_clusters():
    assert cluster_latlon_points([], 2.0, 1) == []


def test_point_beyond_spacing_starts_new_cluster():
    # Clearly beyond min_spacing (haversine rounding makes the exact boundary
    # implementation-defined, so don't pin it).
    pts = [pt(0), pt(2.5)]
    clusters = cluster_latlon_points(pts, min_spacing_m=2.0, min_num_det=1)
    assert len(clusters) == 2
