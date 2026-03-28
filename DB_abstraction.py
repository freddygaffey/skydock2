# this is ai code it was taking to long to make and this is just boilerplate
# so dident write it my self but I did designe the pattens for the methods 

"""
Database abstraction layer using SQLAlchemy.
Provides high-level operations for waypoints, weeds, drone states, and detections.
"""

import sqlite3
from dataclasses import dataclass, field
from typing import ClassVar, Optional, List, Tuple
from sqlalchemy import func
from sqlalchemy.orm import Session

from DB import (
    db_session, WaypointModel, WeedModel, DroneStateModel, DetectionModel, DatabaseSession
)
from drone_state import DroneStateForHoming, Rotation
from ai_class import Frame, Detection
from utils import haversine_distance
from mission_logging import log_event


def _db_mission_log(event: str, **fields) -> None:
    """Mirror DB mutations into mission.jsonl when a mission log is active."""
    try:
        log_event(event, logger="db", level="INFO", **fields)
    except Exception:
        pass


@dataclass
class Waypoint:
    """Waypoint data class for scan pattern navigation"""
    lat: float
    lon: float
    visited: bool = False
    num: int = field(init=False)
    id: Optional[int] = None  # Database ID after persistence
    
    _wp_counter: ClassVar[int] = 0
    
    def __post_init__(self):
        if self.id is None:
            self.num = Waypoint._wp_counter
            Waypoint._wp_counter += 1
        else:
            self.num = self.id
    
    @classmethod
    def from_model(cls, model: WaypointModel) -> "Waypoint":
        """Create Waypoint from SQLAlchemy model"""
        return cls(
            lat=model.lat,
            lon=model.lon,
            visited=model.traveled_to,
            id=model.id
        )
    
    def to_model(self) -> WaypointModel:
        """Convert to SQLAlchemy model"""
        return WaypointModel(
            id=self.id,
            lat=self.lat,
            lon=self.lon,
            traveled_to=self.visited
        )


@dataclass
class Weed:
    """Weed location data class"""
    lat: float
    lon: float
    sprayed: bool = False
    traveled_to: bool = False
    confidence: float = 0.0
    id: Optional[int] = None  # Database ID after persistence
    
    def to_db_format(self):
        """Legacy format for compatibility"""
        return (self.lat, self.lon, int(self.sprayed), int(self.traveled_to))
    
    @classmethod
    def from_model(cls, model: WeedModel) -> "Weed":
        """Create Weed from SQLAlchemy model"""
        return cls(
            lat=model.lat,
            lon=model.lon,
            sprayed=model.sprayed,
            traveled_to=model.traveled_to,
            confidence=model.confidence,
            id=model.id
        )
    
    def to_model(self) -> WeedModel:
        """Convert to SQLAlchemy model"""
        model = WeedModel(
            lon=self.lon,
            lat=self.lat,
            sprayed=self.sprayed,
            traveled_to=self.traveled_to,
            confidence=self.confidence
        )
        if self.id is not None:
            model.id = self.id
        return model


@dataclass
class Snapshot:
    """Combined frame and drone state snapshot"""
    frame: Frame
    drone_state: DroneStateForHoming
    id: Optional[int] = None  # Database ID of the drone state


class DBAbstraction:
    """
    High-level database operations using SQLAlchemy.
    Thread-safe through SQLAlchemy's session management.
    """
    
    def __init__(self, db_path: str = "droneDB.db"):
        """Initialize database connection"""
        self.db_session = DatabaseSession(db_path)
    
    # ===== WAYPOINT OPERATIONS =====
    
    def add_waypoint(self, waypoint: Waypoint) -> int:
        """Add a waypoint and return its ID"""
        with self.db_session.get_session() as session:
            model = waypoint.to_model()
            session.add(model)
            session.flush()  # Get the ID before commit
            waypoint.id = model.id
            _db_mission_log(
                "db_waypoint_add",
                waypoint_id=model.id,
                lat=float(waypoint.lat),
                lon=float(waypoint.lon),
            )
            return model.id
    
    def get_waypoint(self, waypoint_id: int) -> Optional[Waypoint]:
        """Get a waypoint by ID"""
        with self.db_session.get_session() as session:
            model = session.query(WaypointModel).filter_by(id=waypoint_id).first()
            if model:
                return Waypoint.from_model(model)
            return None
    
    def get_next_waypoint(self) -> Optional[Waypoint]:
        """Return the next waypoint by ID that has not been traveled to"""
        with self.db_session.get_session() as session:
            model = (
                session.query(WaypointModel)
                .filter_by(traveled_to=False)
                .order_by(WaypointModel.id)
                .first()
            )
            if model:
                return Waypoint.from_model(model)
            return None
    
    def get_all_waypoints(self) -> List[Waypoint]:
        """Get all waypoints"""
        with self.db_session.get_session() as session:
            models = session.query(WaypointModel).order_by(WaypointModel.id).all()
            return [Waypoint.from_model(m) for m in models]
    
    def mark_waypoint_traveled(self, waypoint: Waypoint):
        """Mark a waypoint as traveled"""
        with self.db_session.get_session() as session:
            session.query(WaypointModel).filter_by(id=waypoint.id).update(
                {"traveled_to": True}
            )
            _db_mission_log("db_waypoint_traveled", waypoint_id=waypoint.id)
    
    # ===== WEED OPERATIONS =====
    
    def log_weed(self, weed: Weed) -> int:
        """Add a weed location and return its ID"""
        with self.db_session.get_session() as session:
            model = weed.to_model()
            session.add(model)
            session.flush()
            weed.id = model.id
            _db_mission_log(
                "db_weed_add",
                weed_id=model.id,
                lat=float(weed.lat),
                lon=float(weed.lon),
                confidence=float(weed.confidence),
            )
            return model.id
    
    def get_weed(self, weed_id: int) -> Optional[Weed]:
        """Get a weed by ID"""
        with self.db_session.get_session() as session:
            model = session.query(WeedModel).filter_by(id=weed_id).first()
            if model:
                return Weed.from_model(model)
            return None
    
    def get_all_weeds(self, sprayed: Optional[bool] = None) -> List[Weed]:
        """Get all weeds, optionally filtered by sprayed status"""
        with self.db_session.get_session() as session:
            query = session.query(WeedModel)
            if sprayed is not None:
                query = query.filter_by(sprayed=sprayed)
            models = query.all()
            return [Weed.from_model(m) for m in models]
    
    def get_closest_weed(
        self, 
        drone_state: DroneStateForHoming,
        only_unsprayed: bool = True
    ) -> Optional[Weed]:
        """Get the closest weed to current drone position"""
        with self.db_session.get_session() as session:
            query = session.query(WeedModel)
            if only_unsprayed:
                query = query.filter_by(sprayed=False, traveled_to=False)
            
            weeds = query.all()
            
            if not weeds:
                return None
            
            min_dist = float("inf")
            closest_weed = None
            
            for weed_model in weeds:
                dist = haversine_distance(
                    weed_model.lat, weed_model.lon,
                    drone_state.latitude, drone_state.longitude
                )
                if dist < min_dist:
                    min_dist = dist
                    closest_weed = weed_model
            
            if closest_weed:
                return Weed.from_model(closest_weed)
            return None
    
    def mark_weed_traveled(self, weed: Weed):
        """Mark a weed as traveled to"""
        with self.db_session.get_session() as session:
            session.query(WeedModel).filter_by(id=weed.id).update(
                {"traveled_to": True}
            )
            _db_mission_log("db_weed_traveled", weed_id=weed.id)
    
    def mark_weed_sprayed(self, weed: Weed):
        """Mark a weed as sprayed"""
        with self.db_session.get_session() as session:
            session.query(WeedModel).filter_by(id=weed.id).update(
                {"sprayed": True}
            )
            _db_mission_log("db_weed_sprayed", weed_id=weed.id)
    
    # ===== DRONE STATE & DETECTION OPERATIONS =====
    
    def log_drone_state_and_frame(
        self, 
        drone_state: DroneStateForHoming, 
        frame: Frame
    ) -> int:
        """
        Log a drone state snapshot with associated detections.
        Returns the drone_state ID.
        """
        with self.db_session.get_session() as session:
            # Create drone state model
            state_model = DroneStateModel(
                time_updated=drone_state.time_updated_GLOBAL_POSITION_INT,
                latitude=drone_state.latitude,
                longitude=drone_state.longitude,
                altitude_rel_home=drone_state.altitude_rel_home,
                velocity_x=drone_state.velocity_x,
                velocity_y=drone_state.velocity_y,
                velocity_z=drone_state.velocity_z,
                enable_homing_and_autonomy=drone_state.enable_homing_and_autonomy,
                heading=drone_state.heading,
                rotation_x=drone_state.rotaion.x,
                rotation_y=drone_state.rotaion.y,
                rotation_z=drone_state.rotaion.z,
                rotation_dx=drone_state.rotaion.dx,
                rotation_dy=drone_state.rotaion.dy,
                rotation_dz=drone_state.rotaion.dz,
                mode=drone_state.mode
            )
            
            session.add(state_model)
            session.flush()  # Get the ID
            
            # Add detections
            for detection in frame.detection:
                # Calculate center from bbox
                center_x = sum(p[0] for p in detection.bbox) / len(detection.bbox)
                center_y = sum(p[1] for p in detection.bbox) / len(detection.bbox)
                
                # Get bbox bounds
                bbox_x1 = min(p[0] for p in detection.bbox)
                bbox_y1 = min(p[1] for p in detection.bbox)
                bbox_x2 = max(p[0] for p in detection.bbox)
                bbox_y2 = max(p[1] for p in detection.bbox)
                
                det_model = DetectionModel(
                    drone_state_id=state_model.id,
                    label=detection.label,
                    confidence=detection.confidence,
                    bbox_x1=bbox_x1,
                    bbox_y1=bbox_y1,
                    bbox_x2=bbox_x2,
                    bbox_y2=bbox_y2,
                    center_x=center_x,
                    center_y=center_y,
                    track_id=detection.track_id,
                    time_detected=detection.time_ns,
                    photo_path=frame.photo_path
                )
                session.add(det_model)
            
            n_det = len(frame.detection)
            _db_mission_log(
                "db_snapshot",
                drone_state_id=state_model.id,
                num_detections=n_det,
                latitude=float(drone_state.latitude),
                longitude=float(drone_state.longitude),
                altitude_rel_home=float(drone_state.altitude_rel_home),
            )
            return state_model.id
    
    def get_all_snapshots(self) -> List[Snapshot]:
        """
        Get all snapshots (drone states with their detections).
        Returns list of Snapshot objects.
        """
        with self.db_session.get_session() as session:
            states = session.query(DroneStateModel).order_by(
                DroneStateModel.time_updated
            ).all()
            
            snapshots = []
            for state_model in states:
                # Reconstruct DroneStateForHoming
                drone_state = DroneStateForHoming(
                    time_updated_GLOBAL_POSITION_INT=state_model.time_updated,
                    latitude=state_model.latitude,
                    longitude=state_model.longitude,
                    altitude_rel_home=state_model.altitude_rel_home,
                    velocity_x=state_model.velocity_x,
                    velocity_y=state_model.velocity_y,
                    velocity_z=state_model.velocity_z,
                    enable_homing_and_autonomy=state_model.enable_homing_and_autonomy,
                    heading=state_model.heading,
                    rotaion=Rotation(
                        time_ns=0,
                        x=state_model.rotation_x,
                        y=state_model.rotation_y,
                        z=state_model.rotation_z,
                        dx=state_model.rotation_dx,
                        dy=state_model.rotation_dy,
                        dz=state_model.rotation_dz,
                    ),
                    mode=state_model.mode
                )

                # Reconstruct Frame with detections
                detections = []
                photo_path = "NO_PHOTO_TAKEN"

                for det_model in state_model.detections:
                    # Reconstruct bbox from bounds
                    bbox = [
                        (det_model.bbox_x1, det_model.bbox_y1),
                        (det_model.bbox_x2, det_model.bbox_y1),
                        (det_model.bbox_x2, det_model.bbox_y2),
                        (det_model.bbox_x1, det_model.bbox_y2)
                    ]
                    
                    detection = Detection(
                        label=det_model.label,
                        confidence=det_model.confidence,
                        bbox=bbox,
                        track_id=det_model.track_id
                    )
                    detection.time_ns = det_model.time_detected
                    detections.append(detection)
                    
                    if det_model.photo_path:
                        photo_path = det_model.photo_path
                
                frame = Frame(det=detections, photo_path=photo_path)
                
                snapshots.append(Snapshot(
                    frame=frame,
                    drone_state=drone_state,
                    id=state_model.id
                ))
            
            return snapshots
    
    def get_latest_snapshot(self) -> Optional[Snapshot]:
        """Get the most recent snapshot"""
        with self.db_session.get_session() as session:
            state_model = (
                session.query(DroneStateModel)
                .order_by(DroneStateModel.time_updated.desc())
                .first()
            )
            
            if not state_model:
                return None
            
            # Reconstruct DroneStateForHoming
            drone_state = DroneStateForHoming(
                time_updated_GLOBAL_POSITION_INT=state_model.time_updated,
                latitude=state_model.latitude,
                longitude=state_model.longitude,
                altitude_rel_home=state_model.altitude_rel_home,
                velocity_x=state_model.velocity_x,
                velocity_y=state_model.velocity_y,
                velocity_z=state_model.velocity_z,
                enable_homing_and_autonomy=state_model.enable_homing_and_autonomy,
                heading=state_model.heading,
                rotaion=Rotation(
                    time_ns=0,
                    x=state_model.rotation_x,
                    y=state_model.rotation_y,
                    z=state_model.rotation_z,
                    dx=state_model.rotation_dx,
                    dy=state_model.rotation_dy,
                    dz=state_model.rotation_dz,
                ),
                mode=state_model.mode
            )

            # Reconstruct Frame with detections
            detections = []
            photo_path = "NO_PHOTO_TAKEN"

            for det_model in state_model.detections:
                bbox = [
                    (det_model.bbox_x1, det_model.bbox_y1),
                    (det_model.bbox_x2, det_model.bbox_y1),
                    (det_model.bbox_x2, det_model.bbox_y2),
                    (det_model.bbox_x1, det_model.bbox_y2)
                ]
                
                detection = Detection(
                    label=det_model.label,
                    confidence=det_model.confidence,
                    bbox=bbox,
                    track_id=det_model.track_id
                )
                detection.time_ns = det_model.time_detected
                detections.append(detection)
                
                if det_model.photo_path:
                    photo_path = det_model.photo_path
            
            frame = Frame(det=detections, photo_path=photo_path)
            
            return Snapshot(
                frame=frame,
                drone_state=drone_state,
                id=state_model.id
            )
    
    # ===== UTILITY OPERATIONS =====
    
    def get_stats(self) -> dict:
        """Get database statistics"""
        with self.db_session.get_session() as session:
            return {
                "total_waypoints": session.query(WaypointModel).count(),
                "traveled_waypoints": session.query(WaypointModel).filter_by(traveled_to=True).count(),
                "total_weeds": session.query(WeedModel).count(),
                "sprayed_weeds": session.query(WeedModel).filter_by(sprayed=True).count(),
                "unsprayed_weeds": session.query(WeedModel).filter_by(sprayed=False).count(),
                "total_snapshots": session.query(DroneStateModel).count(),
                "total_detections": session.query(DetectionModel).count()
            }
    
    def backup_and_clear(self, backup_dir: str = "backups") -> str:
        """
        Backup all data to JSON file, then clear the database.
        Returns the backup file path.
        """
        import json
        import os
        from datetime import datetime

        # Create backup directory if needed
        os.makedirs(backup_dir, exist_ok=True)

        # Generate timestamped filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(backup_dir, f"drone_backup_{timestamp}.json")

        # Collect all data
        backup_data = {
            "timestamp": timestamp,
            "stats": self.get_stats(),
            "waypoints": [],
            "weeds": [],
            "snapshots": []
        }

        # Export waypoints
        for wp in self.get_all_waypoints():
            backup_data["waypoints"].append({
                "id": wp.id,
                "lat": wp.lat,
                "lon": wp.lon,
                "visited": wp.visited
            })

        # Export weeds
        for weed in self.get_all_weeds():
            backup_data["weeds"].append({
                "id": weed.id,
                "lat": weed.lat,
                "lon": weed.lon,
                "sprayed": weed.sprayed,
                "traveled_to": weed.traveled_to,
                "confidence": weed.confidence
            })

        # Export snapshots (drone states + detections)
        for snap in self.get_all_snapshots():
            snapshot_data = {
                "id": snap.id,
                "drone_state": {
                    "time": snap.drone_state.time_updated_GLOBAL_POSITION_INT,
                    "lat": snap.drone_state.latitude,
                    "lon": snap.drone_state.longitude,
                    "alt": snap.drone_state.altitude_rel_home,
                    "velocity_x": snap.drone_state.velocity_x,
                    "velocity_y": snap.drone_state.velocity_y,
                    "velocity_z": snap.drone_state.velocity_z,
                    "enable_homing_and_autonomy": snap.drone_state.enable_homing_and_autonomy,
                    "heading": snap.drone_state.heading,
                    "rotation_x": snap.drone_state.rotaion.x,
                    "rotation_y": snap.drone_state.rotaion.y,
                    "rotation_z": snap.drone_state.rotaion.z,
                    "rotation_dx": snap.drone_state.rotaion.dx,
                    "rotation_dy": snap.drone_state.rotaion.dy,
                    "rotation_dz": snap.drone_state.rotaion.dz,
                    "mode": snap.drone_state.mode
                },
                "detections": []
            }
            for det in snap.frame.detection:
                snapshot_data["detections"].append({
                    "label": det.label,
                    "confidence": det.confidence,
                    "bbox": det.bbox,
                    "track_id": det.track_id
                })
            backup_data["snapshots"].append(snapshot_data)

        # Write backup file
        with open(backup_path, 'w') as f:
            json.dump(backup_data, f, indent=2)

        _db_mission_log("db_backup", backup_path=backup_path)

        # Clear the database
        self.clear_all_data()

        return backup_path

    def clear_all_data(self):
        """Clear all data from database (use with caution!)"""
        st = self.get_stats()
        _db_mission_log("db_clear_all", **{f"before_{k}": v for k, v in st.items()})
        with self.db_session.get_session() as session:
            session.query(DetectionModel).delete()
            session.query(DroneStateModel).delete()
            session.query(WeedModel).delete()
            session.query(WaypointModel).delete()


# Create global singleton instance
db_abstraction = DBAbstraction()


if __name__ == "__main__":
    from telemetry import telemetry_singlton
    import random
    import time
    
    # Initialize database
    db = DBAbstraction()
    
    print("Database initialized!")
    print(f"Stats: {db.get_stats()}")
    
    # Test with random weeds (SITL default location)
    print("\nAdding 10 random weeds near SITL default location...")
    base_lat = -35.3632620
    base_lon = 149.1652370
    
    for _ in range(10):
        # Random offset of ~100m
        lat = base_lat + random.uniform(-0.001, 0.001)
        lon = base_lon + random.uniform(-0.001, 0.001)
        weed = Weed(lat=lat, lon=lon)
        weed_id = db.log_weed(weed)
        print(f"  Added weed {weed_id} at ({lat:.6f}, {lon:.6f})")
    
    print(f"\nUpdated stats: {db.get_stats()}")
    
    # Test finding closest weed
    print("\nTesting closest weed functionality...")
    test_drone_state = DroneStateForHoming()
    test_drone_state.latitude = base_lat
    test_drone_state.longitude = base_lon
    
    closest = db.get_closest_weed(test_drone_state)
    if closest:
        print(f"Closest weed: ID={closest.id}, Location=({closest.lat:.6f}, {closest.lon:.6f})")
    
    print("\nAll tests completed!")