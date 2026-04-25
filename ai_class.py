import threading
import time
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Tuple, Optional

@dataclass
class Detection():
    label: str 
    confidence: float
    bbox: List[Tuple[float, float]]
    track_id: Optional[int] = None
    truth_id: Optional[int] = None
    time_ns: int = field(default_factory=lambda: time.time_ns())

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
                self.time_ns)
         
class Frame:
    def __init__(self, det: list[Detection], photo_path="No photo taken", drone_state=None):
        self.photo_path = photo_path
        self.detection = det
        self.drone_state = drone_state  # state at generation time, for correct back-projection

    def add_detection(self,det:Detection):
        # match "sports ball" or "sports_ball" depending on model format
        if "ball" not in det.label and "frisbee" not in det.label: return
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

    def start_sim_ai(self,sim_weeds: list[list[float]]):
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


if __name__ == "__main__":
    import sys
    sys.modules['ai_class'] = sys.modules['__main__']  # ai_callback imports ai_class — point it here so both share the same singleton
    ai_storage_singleton.start_sim_ai(None)
    print("Waiting for AI pipeline...")

    last_frame = None
    frame_count = 0
    fps_start = time.time()

    while True:
        now = time.time()
        frame = ai_storage_singleton.get_latest_frame()

        if frame is not last_frame:
            last_frame = frame
            frame_count += 1

            if frame.detection:
                for det in frame.detection:
                    cx, cy = det.get_center()
                    print(f"  {det.label} conf={det.confidence:.2f} center=({cx:.0f},{cy:.0f})")

        if now - fps_start >= 1.0:
            fps = frame_count / (now - fps_start)
            frame_count = 0
            fps_start = now
            print(f"FPS: {fps:.1f}  |  {len(frame.detection)} detections")

        time.sleep(0.005)
