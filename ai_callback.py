import threading
import time 

from ai_class import ai_storage, Detection

def mock_callback():
    frame_array = []
    for i in frame:
        frame_array.append(Detection(
            label = "ball",
            confidence = 0.9,
            bbox = [(0.1,0.9),(0.9,0.1)],
            track_id = None,
            photo_path = "palth",
         ))
    ai_storage.add_frame(frame_array)

def start_mock():
    def fun():
        while True: 
            mock_callback()
            time.sleep(0.6)
    threading.Thread(target=fun,daemon=True).start()

# from hailo_wrapper import GStreamerDetectionApp, get_detections_from_buffer
# from gi.repository import Gst

# def my_callback(pad, info, user_data):
#     buffer = info.get_buffer()
#     detections = get_detections_from_buffer(buffer)

#     for det in detections:
#         print(f"Detected: {det.get_label()}")

#     return Gst.PadProbeReturn.OK

# # Start detection
# from hailo_wrapper import user_app_callback_class
# user_data = user_app_callback_class()
# app = GStreamerDetectionApp(my_callback, user_data)
# app.run()