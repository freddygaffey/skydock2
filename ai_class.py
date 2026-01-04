import time
import threading
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Tuple, Optional

# Add parent directory to path for absolute imports (when running directly)
parent_dir = Path(__file__).parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))


class ai_storage():
    def __init__(self):
        self._lock = threading.Lock()
        self._app_thread = None
        self.all_frames = []
        self.current_frame = []
        self._ai_has_started = False

        # photo stuff
        self.take_photo = True
        self.time_last_photo_taken = round(time.time())
        self.rate_take_photo = 1000000000000 # sec
        self.palth_to_save_photo = "/home/fred/skydock/software/photos"

    def take_photo_function(self,palth):
        self.palth_to_save_photo = palth
        self.take_photo = True

    def photo_taken(self,photo_path):
        self.take_photo = False
        self.time_last_photo_taken = round(time.time())


    def photo_not_taken(self):
        if round(time.time()) % self.rate_take_photo == 0 and self.time_last_photo_taken != round(time.time()):
            self.take_photo = True
        self.time_last_photo_taken = round(time.time())
        
    def add_frame(self, frame_arr_objects=None):
        with self._lock:
            thread_name = threading.current_thread().name
            print(f"[{thread_name}] add_frame() BEFORE - current_frame: {len(self.current_frame)}, all_frames: {len(self.all_frames)}")
            if self.current_frame != []:
                self.all_frames.append(self.current_frame.copy())
                print(f"[{thread_name}] add_frame() APPENDED - frame with {len(self.current_frame)} detections")
                self.current_frame = []
            else:
                print(f"[{thread_name}] add_frame() SKIPPED - current_frame was empty")
            print(f"[{thread_name}] add_frame() AFTER - current_frame: {len(self.current_frame)}, all_frames: {len(self.all_frames)}")

    def add_detection(self, label, confidence, bbox, track_id=None,photo_path=None):
        # print("add detection called")
        if photo_path != "NO_PHOTO_TAKEN":
            self.photo_taken(photo_path)
        else:
            self.photo_not_taken()
        
        detection_data = Detection(
            label=label,
            confidence=confidence,
            bbox=bbox,
            track_id=track_id,
            photo_path=photo_path
        )

        # print(f"will ass detection ")
        with self._lock:
            self.current_frame.append(detection_data)
            thread_name = threading.current_thread().name
            print(f"[{thread_name}] add_detection() - Added detection #{len(self.current_frame)} ({label})")
            # print(self.current_frame)
            # print(f"added detection ")

        return detection_data
    
    def get_last_frames(self,num_of_frames=1):
        with self._lock:
            thread_name = threading.current_thread().name
            print(f"[{thread_name}] get_last_frames() - current_frame: {len(self.current_frame)}, all_frames: {len(self.all_frames)}")
            if not self.all_frames:
                print(f"[{thread_name}] get_last_frames() - RETURNING EMPTY - all_frames is empty")
                return []
            if num_of_frames == 1:
                result = self.all_frames[-1].copy()
                print(f"[{thread_name}] get_last_frames() - RETURNING frame with {len(result)} detections")
                return result
            result = self.all_frames[-num_of_frames:].copy()
            print(f"[{thread_name}] get_last_frames() - RETURNING {len(result)} frames")
            return result

    def get_frames_in_time_period(self,more_past,less_past=None):
        # TODO: make faster 
        if not less_past:
            less_past = time.time_ns()
        with self._lock:
            all_frames = self.all_frames.copy()
        frames_to_return = []
        for i in all_frames:
            if i.time_detected >= more_past and i.time_detected <= less_past:
                frames_to_return.append(i)

    def start_ai(self):
        from hailo_apps.hailo_app_python.apps.detection.detection import (
            app_callback,
            user_app_callback_class
        )
        from hailo_apps.hailo_app_python.apps.detection.detection_pipeline import (
            GStreamerDetectionApp
        )
        user_data = user_app_callback_class()
        app = GStreamerDetectionApp(app_callback, user_data)

        self._app_thread = threading.Thread(
            target=app.run,
            daemon=True           # allow program to exit even if thread is running
        )
        if not self._ai_has_started:
            self._app_thread.start()
            self._ai_has_started = True
        else:
            print("ai has allready started")


# ---- SINGLETON INSTANCES CREATED ONCE ----
ai_storage_singleton = ai_storage()
# ai_storage_singleton._ai_storage__start_ai()

# camera_prams = Camera()




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