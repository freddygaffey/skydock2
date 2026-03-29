import json
import math
import os


def generate_scan_path(weed_locations, row_spacing_m=8, padding_m=5):
    """Lawnmower scan path bounding the given weed locations.

    weed_locations: list of {"id": int, "lat": float, "lon": float}
    Returns list of [lat, lon] waypoints.
    """
    lats = [w["lat"] for w in weed_locations]
    lons = [w["lon"] for w in weed_locations]
    mid_lat = sum(lats) / len(lats)

    m_per_deg_lat = 111_111.0
    m_per_deg_lon = 111_111.0 * math.cos(math.radians(mid_lat))

    pad_lat = padding_m / m_per_deg_lat
    pad_lon = padding_m / m_per_deg_lon
    row_step = row_spacing_m / m_per_deg_lat

    min_lat, max_lat = min(lats) - pad_lat, max(lats) + pad_lat
    min_lon, max_lon = min(lons) - pad_lon, max(lons) + pad_lon

    path = []
    lat = min_lat
    left_to_right = True
    while lat <= max_lat + 1e-9:
        a = [round(lat, 8), round(min_lon, 8)]
        b = [round(lat, 8), round(max_lon, 8)]
        path += [a, b] if left_to_right else [b, a]
        left_to_right = not left_to_right
        lat += row_step

    return path


def save_mission(weed_locations, name="real_mission", out_dir="sim_data"):
    """Generate and save a mission file from weed locations.

    Returns the path to the saved file.
    """
    os.makedirs(out_dir, exist_ok=True)

    scan_path = generate_scan_path(weed_locations)
    field_center = [
        sum(w["lat"] for w in weed_locations) / len(weed_locations),
        sum(w["lon"] for w in weed_locations) / len(weed_locations),
    ]

    mission = {
        "field_center": field_center,
        "weed_locations": weed_locations,
        "scan_path": scan_path,
    }

    path = os.path.join(out_dir, f"{name}.json")
    with open(path, "w") as f:
        json.dump(mission, f, indent=2)

    return path
