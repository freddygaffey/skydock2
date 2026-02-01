"""
SQLAlchemy models for the Skydock drone system.
Replaces the raw SQLite implementation with proper ORM patterns.
"""

from sqlalchemy import (
    create_engine, Column, Integer, Float, Boolean, String, ForeignKey, DateTime
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, Session
from datetime import datetime
from typing import Optional, List, Tuple
from contextlib import contextmanager

Base = declarative_base()


class WaypointModel(Base):
    """Waypoint model for scan pattern navigation"""
    __tablename__ = "waypoints"
    
    id = Column(Integer, primary_key=True)
    lon = Column(Float, nullable=False)
    lat = Column(Float, nullable=False)
    traveled_to = Column(Boolean, default=False, nullable=False)
    
    def __repr__(self):
        return f"<Waypoint(id={self.id}, lat={self.lat}, lon={self.lon}, traveled_to={self.traveled_to})>"


class WeedModel(Base):
    """Weed detection location model"""
    __tablename__ = "weeds"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    lon = Column(Float, nullable=False)
    lat = Column(Float, nullable=False)
    sprayed = Column(Boolean, default=False, nullable=False)
    traveled_to = Column(Boolean, default=False, nullable=False)
    
    def __repr__(self):
        return f"<Weed(id={self.id}, lat={self.lat}, lon={self.lon}, sprayed={self.sprayed})>"


class DroneStateModel(Base):
    """Drone telemetry snapshot model"""
    __tablename__ = "drone_states"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    time_updated = Column(Float, nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    altitude_rel_home = Column(Float, nullable=False)
    velocity_x = Column(Float, nullable=False)
    velocity_y = Column(Float, nullable=False)
    velocity_z = Column(Float, nullable=False)
    enable_homing_and_autonomy = Column(Boolean, nullable=False)
    heading = Column(Float, nullable=True)
    rotation_x = Column(Float, nullable=False, default=0.0)
    rotation_y = Column(Float, nullable=False, default=0.0)
    rotation_z = Column(Float, nullable=False, default=0.0)
    
    # Relationship to detections
    detections = relationship("DetectionModel", back_populates="drone_state", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<DroneState(id={self.id}, lat={self.latitude}, lon={self.longitude}, alt={self.altitude_rel_home})>"


class DetectionModel(Base):
    """AI detection model with bounding box and tracking info"""
    __tablename__ = "detections"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    drone_state_id = Column(Integer, ForeignKey("drone_states.id"), nullable=False)
    
    # Detection metadata
    label = Column(String, nullable=True)
    confidence = Column(Float, nullable=True)
    
    # Bounding box coordinates (in pixels, camera is 640x640 square)
    bbox_x1 = Column(Float, nullable=True)
    bbox_y1 = Column(Float, nullable=True)
    bbox_x2 = Column(Float, nullable=True)
    bbox_y2 = Column(Float, nullable=True)
    
    # Center coordinates (in pixels, camera is 640x640 square)
    center_x = Column(Float, nullable=True)
    center_y = Column(Float, nullable=True)
    
    # Tracking
    track_id = Column(Integer, nullable=True)
    time_detected = Column(Integer, nullable=True)  # nanoseconds
    
    # Photo reference
    photo_path = Column(String, nullable=True)
    
    # Relationship to drone state
    drone_state = relationship("DroneStateModel", back_populates="detections")
    
    def __repr__(self):
        return f"<Detection(id={self.id}, label={self.label}, conf={self.confidence}, track_id={self.track_id})>"


class DatabaseSession:
    """
    Database session manager with connection pooling and context management.
    Singleton pattern to ensure one engine per database file.
    """
    _instance = None
    _engine = None
    _session_factory = None
    
    def __new__(cls, db_path: str = "droneDB.db"):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize(db_path)
        return cls._instance
    
    def _initialize(self, db_path: str):
        """Initialize database engine and session factory"""
        self._engine = create_engine(
            f"sqlite:///{db_path}",
            echo=False,  # Set to True for SQL debug logging
            connect_args={"check_same_thread": False}  # Allow multi-threading
        )
        
        # Create all tables
        Base.metadata.create_all(self._engine)
        
        # Create session factory
        self._session_factory = sessionmaker(bind=self._engine)
    
    @contextmanager
    def get_session(self) -> Session:
        """
        Context manager for database sessions.
        Automatically commits on success and rolls back on error.
        
        Usage:
            with db_session.get_session() as session:
                session.add(waypoint)
                # auto-commits here
        """
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()
    
    def get_engine(self):
        """Get the SQLAlchemy engine for advanced operations"""
        return self._engine


# Global database session singleton
db_session = DatabaseSession()


######################### 
# this was my old code it was taking to long and was to much boiler plate so 
# I diden't have time so i got a ai to finish it  
#######################


# import os
# import sqlite3
# from dataclasses import dataclass, field 
# from drone_state import DroneStateForHoming
# from ai_class import Frame
# from utils import haversine_distance
# from typing import ClassVar

# @dataclass
# class Waypoint:
#     lat: float
#     lon: float
#     visited: bool = False
#     num: int = field(init=False)
    
#     _wp_counter: ClassVar[int] = 0
    
#     def __post_init__(self):
#         self.num = Waypoint._wp_counter
#         Waypoint._wp_counter += 1

# @dataclass
# class Weed:
#     lon: float
#     lat: float
#     sprayed: bool = False
#     traveled_to: bool = False
    
#     def to_db_format(self):
#         return (self.lon, self.lat, int(self.sprayed), int(self.traveled_to))

# @dataclass
# class Snapshot:
#     frame:Frame
#     drone_state:DroneStateForHoming

# class DBAbstrction:
#     def __init__(self):
#         self.db = sqlite3.connect("droneDB.db")
#         self._make_table()
        
#     def _make_table(self):
#         # make waypoints table
#         self.db.execute("""CREATE TABLE IF NOT EXISTS
#                         waypoints (
#                             id INTEGER PRIMARY KEY,
#                             lon REAL NOT NULL,
#                             lat REAL NOT NULL,
#                             traveled_to INTEGER DEFAULT 0)""")
#         # make weeds table
#         self.db.execute("""CREATE TABLE IF NOT EXISTS
#                         weeds (
#                             id INTEGER PRIMARY KEY AUTOINCREMENT,
#                             lon REAL NOT NULL,
#                             lat REAL NOT NULL,
#                             sprayed INTEGER DEFAULT 0,
#                             traveled_to INTEGER DEFAULT 0)""")

#         # make drone states table
#         self.db.execute("""CREATE TABLE IF NOT EXISTS
#                         drone_state (
#                             id INTEGER PRIMARY KEY,
#                             time_updated REAL NOT NULL,
#                             latitude REAL NOT NULL,
#                             longitude REAL NOT NULL,
#                             altitude_rel_home REAL NOT NULL,
#                             velocity_x REAL NOT NULL,
#                             velocity_y REAL NOT NULL,
#                             velocity_z REAL NOT NULL,
#                             enable_homing_and_autonomy INTEGER NOT NULL,
#                             heading REAL,
#                             rotation_x REAL NOT NULL,
#                             rotation_z REAL NOT NULL,
#                             rotation_y REAL NOT NULL
#                         )""")

#         # make a detecton table
#         self.db.execute("""CREATE TABLE IF NOT EXISTS 
#                                 detections (
#                                     id INTEGER PRIMARY KEY AUTOINCREMENT,
#                                     drone_state_id INTEGER NOT NULL,
#                                     label TEXT,
#                                     confidence REAL,
#                                     bbox_x1 REAL,
#                                     bbox_y1 REAL,
#                                     bbox_x2 REAL,
#                                     bbox_y2 REAL,
#                                     center_x REAL,
#                                     center_y REAL,
#                                     track_id INTEGER,
#                                     time_detected INTEGER,
#                                     photo_path TEXT,
#                                     FOREIGN KEY (drone_state_id) REFERENCES drone_states(id)
#                                     )""")

#     def get_closest_weed(self, drone_state: DroneStateForHoming = None) -> Weed:
#         all_weeds = self.db.execute("SELECT * FROM weeds")
#         min_dist = float("inf")
#         print(drone_state)
#         best_weed = None
#         for i in all_weeds:
#             i = i[1:]
#             weed = Weed(*i)
#             if (dist := haversine_distance(weed.lon, weed.lat, drone_state.latitude, drone_state.longitude)) <= min_dist:
#                 best_weed = weed 
#                 min_dist = dist
#         return weed

#     def get_next_way_point(self) -> Waypoint:
#         """retun the next way point by id that has not been traveled to"""
#         ...

#     def get_all_snapshot(self)-> list[Snapshot]:
#         ...

#     def log_drone_state_and_frame(self,drone_state:DroneStateForHoming,frame:Frame):
#         for i in frame.detection:
#             self.db.execute("")
#         ...

#     def log_weed(self,weed:Weed):
#         cur = self.db.execute("INSERT INTO weeds (lon,lat,sprayed,traveled_to) VALUES (?, ?, ?, ?)", weed.to_db_format())
#         self.db.commit()
#         return cur.lastrowid
        
#     def waypoint_traveled_to(self,waypiont:Waypoint):
#         ...

#     def weed_traveled_to(self,weed:Weed):
#         ...

#     def weed_sprayed(self,weed:Weed):
#         ...

# if __name__ == "__main__":
#     from telemetry import telemetry_singlton
#     import random
#     import time
#     while True: 
#         db_class = DBAbstrction()
#         db_class._make_table()
#         exit()
        
#         # SITL default in degE7 (int32)
#         base_lat = -353632620
#         base_lon = 1491652370
        
#         for _ in range(10):
#             # Random offset of ~100m (roughly 1000 in degE7 ≈ 0.0001° ≈ 11m)
#             lat = base_lat + random.randint(-10000, 10000)
#             lon = base_lon + random.randint(-10000, 10000)
#             # Convert back to float degrees for your Weed class
#             db_class.log_weed(Weed(lon=lon / 1e7, lat=lat / 1e7))
        
#         closest = db_class.get_closest_weed(telemetry_singlton.drone_state)
#         print(f"Closest weed: {closest}")
#         time.sleep(1)
        