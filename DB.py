import os
import sqlite3
from dataclasses import dataclass, field 
from drone_state import DroneStateForHoming
from ai_class import Frame
from utils import haversine_distance
from typing import ClassVar

@dataclass
class Waypoint:
    lat: float
    lon: float
    visited: bool = False
    num: int = field(init=False)
    
    _wp_counter: ClassVar[int] = 0
    
    def __post_init__(self):
        self.num = Waypoint._wp_counter
        Waypoint._wp_counter += 1

@dataclass
class Weed:
    lon: float
    lat: float
    sprayed: bool = False
    traveled_to: bool = False
    
    def to_db_format(self):
        return (self.lon, self.lat, int(self.sprayed), int(self.traveled_to))

@dataclass
class Snapshot:
    frame:Frame
    drone_state:DroneStateForHoming

class DBAbstrction:
    def __init__(self):
        self.db = sqlite3.connect("droneDB.db")
        self._make_table()
        
    def _make_table(self):
        # make waypoints table
        self.db.execute("""CREATE TABLE IF NOT EXISTS
                        waypoints (
                            id INTEGER PRIMARY KEY,
                            lon REAL NOT NULL,
                            lat REAL NOT NULL,
                            traveled_to INTEGER DEFAULT 0)""")
        # make weeds table
        self.db.execute("""CREATE TABLE IF NOT EXISTS
                        weeds (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            lon REAL NOT NULL,
                            lat REAL NOT NULL,
                            sprayed INTEGER DEFAULT 0,
                            traveled_to INTEGER DEFAULT 0)""")

        # make drone states table
        self.db.execute("""CREATE TABLE IF NOT EXISTS
                        drone_state (
                            id INTEGER PRIMARY KEY,
                            time_updated REAL NOT NULL,
                            latitude REAL NOT NULL,
                            longitude REAL NOT NULL,
                            altitude_rel_home REAL NOT NULL,
                            velocity_x REAL NOT NULL,
                            velocity_y REAL NOT NULL,
                            velocity_z REAL NOT NULL,
                            enable_homing_and_autonomy INTEGER NOT NULL,
                            heading REAL,
                            rotation_x REAL NOT NULL,
                            rotation_z REAL NOT NULL,
                            rotation_y REAL NOT NULL
                        )""")

        # make a detecton table
        self.db.execute("""CREATE TABLE IF NOT EXISTS 
                                detections (
                                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                                    drone_state_id INTEGER NOT NULL,
                                    label TEXT,
                                    confidence REAL,
                                    bbox_x1 REAL,
                                    bbox_y1 REAL,
                                    bbox_x2 REAL,
                                    bbox_y2 REAL,
                                    center_x REAL,
                                    center_y REAL,
                                    track_id INTEGER,
                                    time_detected INTEGER,
                                    photo_path TEXT,
                                    FOREIGN KEY (drone_state_id) REFERENCES drone_states(id)
                                    )""")

    def get_closest_weed(self, drone_state: DroneStateForHoming = None) -> Weed:
        all_weeds = self.db.execute("SELECT * FROM weeds")
        min_dist = float("inf")
        print(drone_state)
        best_weed = None
        for i in all_weeds:
            i = i[1:]
            weed = Weed(*i)
            if (dist := haversine_distance(weed.lon, weed.lat, drone_state.latitude, drone_state.longitude)) <= min_dist:
                best_weed = weed 
                min_dist = dist
        return weed

    def get_next_way_point(self) -> Waypoint:
        """retun the next way point by id that has not been traveled to"""
        ...

    def get_all_snapshot(self)-> list[Snapshot]:
        ...

    def log_drone_state_and_frame(self,drone_state:DroneStateForHoming,frame:Frame):
        for i in frame.detection:
            self.db.execute("")
        ...

    def log_weed(self,weed:Weed):
        cur = self.db.execute("INSERT INTO weeds (lon,lat,sprayed,traveled_to) VALUES (?, ?, ?, ?)", weed.to_db_format())
        self.db.commit()
        return cur.lastrowid
        
    def waypoint_traveled_to(self,waypiont:Waypoint):
        ...

    def weed_traveled_to(self,weed:Weed):
        ...

    def weed_sprayed(self,weed:Weed):
        ...

if __name__ == "__main__":
    from telemetry import telemetry_singlton
    import random
    import time
    while True: 
        db_class = DBAbstrction()
        db_class._make_table()
        exit()
        
        # SITL default in degE7 (int32)
        base_lat = -353632620
        base_lon = 1491652370
        
        for _ in range(10):
            # Random offset of ~100m (roughly 1000 in degE7 ≈ 0.0001° ≈ 11m)
            lat = base_lat + random.randint(-10000, 10000)
            lon = base_lon + random.randint(-10000, 10000)
            # Convert back to float degrees for your Weed class
            db_class.log_weed(Weed(lon=lon / 1e7, lat=lat / 1e7))
        
        closest = db_class.get_closest_weed(telemetry_singlton.drone_state)
        print(f"Closest weed: {closest}")
        time.sleep(1)
        