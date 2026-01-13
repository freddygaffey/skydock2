import time
import threading
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Tuple, Optional
from json import dump

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

class Frame:
    def __init__(self,det:list[Detection],photo_path):
        self.photo_path = photo_path
        self.detection = det

    def add_detection(self,det:Detection):
        self.detection.append(det)

class AiStorage:
    def __init__(self):
       self.is_ai_running = False
       
       self.current_frame = None
       self.current_frame_lock = threading.Lock()

    def take_photo(self): ...

    def set_latest_frame(self,frame:Frame):
        with current_frame_lock:
            threading.Thread(target=self.write_to_db,args=(self.current_frame))
            self.current_frame = frame

    def write_to_db(self,frame):
        pass 
        
        


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

    
# class _Ai_storage:

#     def __init__(self):
#        self.frame_array: List[Frame] = []
#        self.frame_array_lock = threading.Lock()
#        self.is_ai_running = False

#        self.take_photo = False
#        self.photo_taken_last_frame = False

#     def add_frame(self, frame: Frame):
#         # print(f"add_frame called on class id: {id(self)}")  # ADD THIS
#         # print(f"frame_array id: {id(self.frame_array)}")     # ADD THIS

#         if frame.photo_path != "NO_PHOTO_TAKEN":
#             self.photo_taken_last_frame = True
#         else:
#             self.photo_taken_last_frame = False
#         with self.frame_array_lock:
#             self.frame_array.append(frame)
#             # print(self.frame_array)
#         # print("added frame ") 
        
#     def get_frame_array(self):
#         with self.frame_array_lock: 
#             return self.frame_array

#     def get_frame_array_copy(self):
#         with self.frame_array_lock: 
#             return self.frame_array.copy()

#     def start_ai(self):
#         if self.is_ai_running == True:
#             print("ai is allreday running")
#             # raise SystemError("the ai is allready running")

#         self.is_ai_running = True
#         ######## I dont understand but it works thanks ai #########
#         import sys
#         import ai_callback
#         # Force it to use THIS module's ai_storage
#         sys.modules['ai_callback'].ai_storage = self
#         ############################################################

#         app = ai_callback.make_ai_app()
#         threading.Thread(target=app.run).start()

# ai_storage = _Ai_storage() 
# ai_storage.start_ai()

# if __name__ == "__main__":
#     print(f"Main: ai_storage instance id: {id(ai_storage)}")  # ← ADD THIS
#     print(f"Main: frame_array id: {id(ai_storage.frame_array)}")  # ← ADD THIS
    
#     ai_storage.start_ai()
#     time.sleep(2)
    
#     while True:
#         print(ai_storage.get_frame_array())
