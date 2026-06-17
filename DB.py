"""
SQLAlchemy models for the Skydock drone system.
Replaces the raw SQLite implementation with proper ORM patterns.
"""

from sqlalchemy import (
    create_engine, Column, Integer, Float, Boolean, String, ForeignKey
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, Session
from contextlib import contextmanager

Base = declarative_base()

_db_path = "droneDB.db"


def set_db_path(path: str) -> None:
    """Set the DB file path before the singleton is first instantiated."""
    global _db_path
    _db_path = path


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
    confidence = Column(Float, default=0.0, nullable=False)

    def __repr__(self):
        return f"<Weed(id={self.id}, lat={self.lat}, lon={self.lon}, sprayed={self.sprayed}, confidence={self.confidence})>"


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
    autonomy_enabled = Column(Boolean, nullable=False)
    heading = Column(Float, nullable=True)
    rotation_x = Column(Float, nullable=False, default=0.0)
    rotation_y = Column(Float, nullable=False, default=0.0)
    rotation_z = Column(Float, nullable=False, default=0.0)
    rotation_dx = Column(Float, nullable=False, default=0.0)
    rotation_dy = Column(Float, nullable=False, default=0.0)
    rotation_dz = Column(Float, nullable=False, default=0.0)
    mode = Column(String, nullable=True)
    
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
    
    # Bounding box coordinates (in pixels; frame is DroneStateForHoming.width x .height, default 1280x1280)
    bbox_x1 = Column(Float, nullable=True)
    bbox_y1 = Column(Float, nullable=True)
    bbox_x2 = Column(Float, nullable=True)
    bbox_y2 = Column(Float, nullable=True)
    
    # Center coordinates (in pixels; frame is DroneStateForHoming.width x .height, default 1280x1280)
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
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize(_db_path)
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


# Note: DatabaseSession is instantiated lazily by DBAbstraction after set_db_path() is called.

