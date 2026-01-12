import time
import threading
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Tuple, Optional

@dataclass
class Detection():
    label: str 
    confidence: float
    bbox: List[Tuple[float, float]]
    track_id: Optional[int] = None

    time_detected: int = field(default_factory=lambda: time.time_ns())

class Camera:
    x_flip  = 1 # 1 is not flip -1 is flip
    y_flip  = 1
    x_dist_per_pix_per_meter: float = 0.0003792011843564136 * x_flip
    y_dist_per_pix_per_meter: float = 0.0005137066016141622 * y_flip
    fov_x: float = 27.4   # degrees
    fov_y: float = 21.0   # degrees
    width: int = 1280
    height: int = 720

class Frame:
    def __init__(self,det:list[Detection],photo_path):
        self.photo_path = photo_path
        self.detection = det

    def add_detection(self,det:Detection):
        self.detection.append(det)
        
class _Ai_storage:
    """Private class - do not instantiate directly. Use the ai_storage singleton."""

    def __init__(self):
       self.frame_array: List[Frame] = []
       self.frame_array_lock = threading.Lock()
       self.is_ai_running = False

       self.take_photo = False
       self.photo_taken_last_frame = False

    def add_frame(self, frame: Frame):
        # print(f"add_frame called on class id: {id(self)}")  # ADD THIS
        # print(f"frame_array id: {id(self.frame_array)}")     # ADD THIS

        if frame.photo_path != "NO_PHOTO_TAKEN":
            self.photo_taken_last_frame = True
        else:
            self.photo_taken_last_frame = False
        with self.frame_array_lock:
            self.frame_array.append(frame)
            # print(self.frame_array)
        # print("added frame ") 
        
    def get_frame_array(self):
        with self.frame_array_lock: 
            return self.frame_array

    def get_frame_array_copy(self):
        with self.frame_array_lock: 
            return self.frame_array.copy()

    def start_ai(self):
        if self.is_ai_running == True:
            print("ai is allreday running")
            # raise SystemError("the ai is allready running")

        self.is_ai_running = True
        ######## I dont understand but it works thanks ai #########
        import sys
        import ai_callback
        # Force it to use THIS module's ai_storage
        sys.modules['ai_callback'].ai_storage = self
        ############################################################

        app = ai_callback.make_ai_app()
        threading.Thread(target=app.run).start()

ai_storage = _Ai_storage() 
ai_storage.start_ai()

if __name__ == "__main__":
    print(f"Main: ai_storage instance id: {id(ai_storage)}")  # ← ADD THIS
    print(f"Main: frame_array id: {id(ai_storage.frame_array)}")  # ← ADD THIS
    
    ai_storage.start_ai()
    time.sleep(2)
    
    while True:
        print(ai_storage.get_frame_array())
