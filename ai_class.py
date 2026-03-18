import threading
import time
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Tuple, Optional
from mission_logging import allocate_mission_dir, configure_mission_dir

# Setup missions directory - relative to project, SD-card style numbering
_project_root = Path(__file__).resolve().parent
session_dir = allocate_mission_dir(_project_root)
configure_mission_dir(session_dir)
frames_dir = session_dir / "frames"
os.makedirs(session_dir, exist_ok=True)
os.makedirs(frames_dir, exist_ok=True)


@dataclass
class Detection():
    label: str 
    confidence: float
    bbox: List[Tuple[float, float]]
    track_id: Optional[int] = None
    time_detected: int = field(default_factory=lambda: time.time_ns())

    def get_center(self):
        x = (self.bbox[0][0] + self.bbox[1][0]) / 2
        y = (self.bbox[0][1] + self.bbox[1][1]) / 2
        return x , y

    def to_db_format(self):
        center = self.get_center()
        return (self.label,
                self.confidence,
                self.bbox[0][0], 
                self.bbox[0][1],
                self.bbox[1][0],
                self.bbox[1][1],
                center[0],
                center[1],
                self.track_id,
                self.time_detected)
         
class Frame:
    def __init__(self,det:list[Detection],photo_path="No photo taken"):
        self.photo_path = photo_path
        self.detection = det

    def add_detection(self,det:Detection):
        if det.label not in ["sports ball", "frisbee", "person"]: return
        self.detection.append(det)


class _AiStorage:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        self._initialized = True

        self.current_frame = Frame([])
        self.current_frame_lock = threading.Lock()
        self.is_ai_running = False

    def take_photo(self):
        ...

    def set_latest_frame(self, frame: Frame):
        with self.current_frame_lock:
            self.current_frame = frame

    def get_latest_frame(self) -> Frame | None:
        with self.current_frame_lock:
            return self.current_frame

    def start_ai(self,sim_weeds: list[list[float]]):
        if self.is_ai_running:
            print("ai is already running")
            return

        self.is_ai_running = True
        if sim_weeds is not None and len(sim_weeds) > 0:
            from sim_ai import run_sim_ai
            run_sim_ai(sim_weeds)
            return

        ######## I dont understand but it works thanks ai #########
        # import sys
        import ai_callback
        # Force it to use THIS module's ai_storage
        # sys.modules['ai_callback'].ai_storage = self
        ############################################################
        app = ai_callback.make_ai_app()
        threading.Thread(target=app.run).start()


ai_storage_singleton = _AiStorage()




