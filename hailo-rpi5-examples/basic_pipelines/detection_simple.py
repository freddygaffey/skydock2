# from ai_class import ai_storage, Frame, Detection
from ai_class import ai_storage_singleton, Detection, Frame

import time
import os
from pathlib import Path
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst
import hailo
from hailo_apps.hailo_app_python.core.gstreamer.gstreamer_app import app_callback_class
from hailo_apps.hailo_app_python.apps.detection_simple.detection_pipeline_simple import GStreamerDetectionApp

# User-defined class to be used in the callback function: Inheritance from the app_callback_class
class user_app_callback_class(app_callback_class):
    def __init__(self):
        super().__init__()

# User-defined callback function: This is the callback function that will be called when data is available from the pipeline
def app_callback(pad, info, user_data):

    buffer = info.get_buffer()  # Get the GstBuffer from the probe info
    if buffer is None:  # Check if the buffer is valid
        return Gst.PadProbeReturn.OK

    caps = pad.get_current_caps()
    structure = caps.get_structure(0)
    width = structure.get_value('width')
    height = structure.get_value('height')
    
    frame = Frame([])
    for detection in hailo.get_roi_from_buffer(buffer).get_objects_typed(hailo.HAILO_DETECTION):  
        label = str(detection.get_label())
        # print(f"seen {label}")
        # if label not in ["sports_ball","frisby","person"]: continue
        # if label not in ["sports_ball","frisby"]: continue
        # print(f"saved {label}")
        bbox = detection.get_bbox()
        bbox = [(bbox.xmin() * width, bbox.ymin() * height),
                (bbox.xmax() * width, bbox.ymax() * height)]

        confidence = float(detection.get_confidence())
        det = Detection(label=label,confidence=confidence,bbox=bbox) 
        frame.add_detection(det)

    ai_storage_singleton.set_latest_frame(frame) 
    return Gst.PadProbeReturn.OK

def make_ai_app():
    project_root = Path(__file__).resolve().parent.parent
    env_file     = project_root / ".env"
    env_path_str = str(env_file)
    os.environ["HAILO_ENV_FILE"] = env_path_str
    user_data = user_app_callback_class()  
    app = GStreamerDetectionApp(app_callback, user_data)
    return app
    

if __name__ == "__main__":
    import threading
    th = threading.Thread(target=make_ai_app().run)
    th.start()
    while True:
        try:
            for i in ai_storage_singleton.get_latest_frame().detection:
                print(i.label)
        except AttributeError:
            print("passing atribuie error")
        except KeyboardInterrupt:
            th.stop()
             
