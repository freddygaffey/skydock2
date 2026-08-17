from dataclasses import dataclass
from ai_class import Detection

from telemetry import telemetry_singleton
from drone_state import DroneStateForHoming
from ai_class import Frame
from DB_abstraction import db_abstraction, Weed
from utils import detection_to_latlon, haversine_distance
from constants import SCAN_HEIGHT, MIN_DIST_FROM_WAYPOINT, MIN_WEED_SPACING, MIN_NUM_DET, GOTO_ALT, TARGET_SIM_SPEED
from states.enum import DroneStateEnum
from mission_logging import log_event

_scan_data_processed = False

def scan(drone_state:DroneStateForHoming,frame:Frame):
    """Fly the lawnmower waypoints, logging a snapshot each tick.

    Flies to the next un-traveled waypoint at SCAN_HEIGHT and marks it traveled
    within MIN_DIST_FROM_WAYPOINT. When all waypoints are done, holds position,
    runs process_all_scan_data() once to cluster detections into weeds, then
    returns GOTO.
    """
    global _scan_data_processed
    point = db_abstraction.get_next_waypoint()
    if point == None:
        if not _scan_data_processed:
            print("processing all data")
            telemetry_singleton.fly_to_point(drone_state.latitude,drone_state.longitude,GOTO_ALT)
            process_all_scan_data()
            print("process_all_scan_data is complete")
            _scan_data_processed = True
            import time
            time.sleep(10/TARGET_SIM_SPEED)
        return DroneStateEnum.GOTO
    db_abstraction.log_drone_state_and_frame(frame.drone_state or drone_state,frame)

    telemetry_singleton.fly_to_point(point.lat,point.lon,SCAN_HEIGHT)
    if MIN_DIST_FROM_WAYPOINT > (haversine_distance(drone_state.latitude,drone_state.longitude,point.lat,point.lon)):
        db_abstraction.mark_waypoint_traveled(point)

    return DroneStateEnum.SCAN


@dataclass
class detState:
    det: Detection
    state: DroneStateForHoming

@dataclass
class Point:
    location: list[tuple[float, float]] = None # lat lon
    det_location: list = None # [lat, lon]

    def add_det(self,lat,lon):
        if self.det_location is None:
            self.det_location = []
        self.det_location.append((lat,lon))
        lat_s, lon_s = zip(*self.det_location)
        cnt = len(self.det_location)
        self.location = (sum(lat_s)/cnt, sum(lon_s)/cnt)

    def dist_to_cord(self,poss):
        return haversine_distance(*self.location,*poss)


def cluster_latlon_points(det_locs, min_spacing_m: float, min_num_det: int) -> list[Point]:
    """Greedily group (lat, lon) points within min_spacing_m into running-centroid
    clusters; drop clusters with fewer than min_num_det points. Order-dependent
    by design (matches in-flight behaviour); tools/tune_clustering.py sweeps the
    two thresholds over recorded flights using this exact function."""
    all_points: list[Point] = []
    for det_loc in det_locs:
        min_dist = float("inf")
        min_point = None
        for j in all_points:
            d = j.dist_to_cord(det_loc)
            if d < min_dist:
                min_point = j
                min_dist = d
        if min_dist < min_spacing_m and min_point is not None:
            min_point.add_det(*det_loc)
        else:
            new_point = Point()
            new_point.add_det(*det_loc)
            all_points.append(new_point)
    return [p for p in all_points if len(p.det_location) >= min_num_det]


def snapshots_to_latlon_points(frame_state) -> list[tuple[float, float]]:
    """Back-project every snapshot detection to lat/lon, dropping non-finite ones."""
    import math
    det_locs = []
    for i in frame_state:
        for j in i.frame.detection:
            det_loc = detection_to_latlon(i.drone_state, j)
            if math.isfinite(det_loc[0]) and math.isfinite(det_loc[1]):
                det_locs.append(det_loc)
    return det_locs


def process_all_scan_data():
    """Cluster all logged detections into weeds and persist them.

    Back-projects every detection to lat/lon, greedily groups points within
    MIN_WEED_SPACING into running-centroid clusters, drops clusters with fewer
    than MIN_NUM_DET detections, and logs each survivor as a weed.
    """
    det_locs = snapshots_to_latlon_points(db_abstraction.get_all_snapshots())
    all_points = cluster_latlon_points(det_locs, MIN_WEED_SPACING, MIN_NUM_DET)
    for i in all_points:
        weed = Weed(lat=i.location[0], lon=i.location[1])
        db_abstraction.log_weed(weed)
        # print(f"[PROCESS]   keep weed lat={i.location[0]:.6f} lon={i.location[1]:.6f} dets={len(i.det_location)}")
        log_event(
            "weed_detected",
            logger="ai",
            level="INFO",
            drone_state=None,
            frame=None,
            weed={"lat": float(i.location[0]), "lon": float(i.location[1])},
            num_detections=len(i.det_location) if i.det_location is not None else None,
        )

    print(f"[PROCESS] DONE: {len(all_points)} weed(s) detected")
    for idx, i in enumerate(all_points):
        print(f"weed #{idx} lat={i.location[0]:.6f} lon={i.location[1]:.6f} dets={len(i.det_location)}")
