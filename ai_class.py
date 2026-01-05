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
    photo_path: Optional[str] = None

    time_detected: int = field(default_factory=lambda: time.time_ns())
    # vector_to_center: Tuple[float, float] = field(init=False)  # computed after init

    # def __post_init__(self):
    #     self.vector_to_center = self.get_the_vector_center()

    def get_the_vector_center(self):
        cx = Camera.width / 2
        cy = Camera.height / 2

        bbx = (self.bbox[0][0] + self.bbox[1][0]) / 2
        bby = (self.bbox[0][1] + self.bbox[1][1]) / 2

        return (bbx - cx, bby - cy) 


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
    def __init__(self,det:list[Detection],photo_palth):
        self.photo_palth = photo_palth
        self.detection = det

    def add_detection(self,det:Detection):
        self.detection.append(det)
        


class ai_storage:
    frame_array: List[Frame] = []
    frame_array_lock = threading.Lock()
    is_ai_running = False

    take_photo = False
    photo_taken_last_frame = False

    @classmethod     
    def add_frame(cls,frame:Frame):
        print("added frame ") 
        if frame.photo_palth != "NO_PHOTO_TAKEN":
            cls.photo_taken_last_frame = True
            
        else: cls.photo_taken_last_frame = False

        with cls.frame_array_lock:
            cls.frame_array.append(frame)

    @classmethod
    def start_ai(cls):
        if cls.is_ai_running == True:
            raise SystemError("the ai is allready running")

        cls.is_ai_running = True
        from ai_callback import start_ai
        threading.Thread(target=start_ai,daemon=True).start()

if __name__ == "__main__":
    ai_storage.start_ai()
    while True:
        print(ai_storage.__dict__)

    




if __name__ == "__main__":
    # from ai import ai_storage_singleton
    ai_storage_singleton.start_ai()
    while True:
        time.sleep(0.5)

        last_frames = ai_storage_singleton.get_last_frames(1)
        print(f"Last frames: {last_frames}\n")
        # print(last_frames)



        # if not last_frames:
        #     print("is none")
        #     continue
        # else:
        #     print(type(last_frames))
        #     for i in last_frames[0]:
        #         print(i)
        #         print("\n")
        #     print("-"*10)