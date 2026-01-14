import os
import sqlite3
from dataclasses import dataclass 
from drone_state import DroneStateForHoming
from ai_class import Frame

class Waypoint:
    wp_num = 0 
    def __init__(self,gps: tuple[float,float]):
        self.poss = gps
        self.num = Waypoint.wp_num
        Waypoint.wp_num += 1
        self.visited = False

@dataclass
class Weed:
    def __init__(self, gps: tuple[float,float]):
        self.poss = gps
        self.sprayed = False

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
                            sprayed INTEGER DEFAULT 0)""")

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
                            rotation_yaw REAL NOT NULL
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

    def get_closest_weed(self, drone_state: DroneStateForHoming) -> Weed:
        ...

    def get_next_way_point(self) -> Waypoint:
        """retun the next way point by id that has not been traveled to"""
        ...

    def get_all_snapshot(self)-> list[Snapshot]:
        ...

    def log_drone_state_and_frame(self,drone_state:DroneStateForHoming,frame:Frame):
        ...

    def log_weed(self,weed:Weed):
        ...

    def waypoint_traveled_to(self,waypiont:Waypoint):
        ...

    def weed_traveled_to(self,weed:Weed):
        ...
        return self.get_next_weed()

    def weed_sprayed(self,weed:Weed):
        ...
    
    
if __name__ == "__main__":
    db_class = DBAbstrction()