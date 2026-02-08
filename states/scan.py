from dataclasses import dataclass
from ai_class import Detection

from telemetry import telemetry_singlton
from drone_state import DroneStateForHoming
from ai_class import Frame
from DB_abstraction import db_abstraction, Weed
from utils import detection_to_latlon, haversine_distance, detection_to_ned
from states.constants import SCAN_HIGHT, MIN_DIST_FROM_WAYPOINT, MIN_WEED_SPACING, MIN_NUM_DET
from states.enum import DroneStateEnum

_scan_data_processed = False

def scan(drone_state:DroneStateForHoming,frame:Frame):
    global _scan_data_processed
    point = db_abstraction.get_next_waypoint()
    if point == None:
        if not _scan_data_processed:
            print("prosesing all data")
            prosess_all_scan_data()
            print("prosess_all_scan_data is compleate")
            _scan_data_processed = True
        return DroneStateEnum.GOTO
    db_abstraction.log_drone_state_and_frame(drone_state,frame)

    telemetry_singlton.fly_to_point(point.lat,point.lon,SCAN_HIGHT)
    if MIN_DIST_FROM_WAYPOINT > (haversine_distance(drone_state.latitude,drone_state.longitude,point.lat,point.lon)):
        db_abstraction.mark_waypoint_traveled(point)

    return DroneStateEnum.SCAN


@dataclass
class detState:
    det: Detection
    state: DroneStateForHoming

@dataclass
class Point:
    location: list = None # lat lon
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

def prosess_all_scan_data():
    all_points = []
    frame_state = db_abstraction.get_all_snapshots()
    all_det = []
    for i in frame_state:
        for j in i.frame.detection:
            all_det.append(detState(j,i.drone_state))
    for i in all_det:
        det_loc = detection_to_latlon(i.state,i.det)
        min_dist = float("inf")
        min_point = None
        for j in all_points:
            if j.dist_to_cord(det_loc) < min_dist:
                min_point = j
                min_dist = j.dist_to_cord(det_loc)
        if min_dist < MIN_WEED_SPACING and min_point is not None:
            min_point.add_det(*det_loc)
        else:
           new_point = Point()
           new_point.add_det(*det_loc)
           all_points.append(new_point)     
    to_remove = []
    for i in all_points:
        if len(i.det_location) < MIN_NUM_DET:
            to_remove.append(i)
    for i in to_remove: all_points.remove(i)
    for i in all_points:
        weed = Weed(lat=i.location[0], lon=i.location[1])
        db_abstraction.log_weed(weed)