# from ai_class import ai_storage, Frame, Detection
from ai_class import ai_storage_singleton, Detection, Frame
from mission_logging import get_mission_dir

import threading
import time
import os
from pathlib import Path
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst
import hailo
from hailo_apps.hailo_app_python.core.gstreamer.gstreamer_app import app_callback_class
from hailo_apps.hailo_app_python.apps.detection_simple.detection_pipeline_simple import GStreamerDetectionApp

import numpy as np
import cv2
import queue as queue_module  # rename to avoid shadowing

# Frame saving queue
frame_queue = queue_module.Queue(maxsize=200)

def frame_saver_thread():
    """Background thread - saves frames as JPEG"""
    while True:
        try:
            timestamp_ns, data, width, height = frame_queue.get(timeout=2)
            mission_dir = get_mission_dir()
            if mission_dir is None:
                continue
            frames_dir = mission_dir / "frames"
            frames_dir.mkdir(exist_ok=True)
            frame = np.frombuffer(data, dtype=np.uint8).reshape((height, width, 3))
            cv2.imwrite(str(frames_dir / f"{timestamp_ns}.jpg"), frame)
        except queue_module.Empty:
            continue

# Start the saver thread
threading.Thread(target=frame_saver_thread, daemon=True).start()

# User-defined class to be used in the callback function: Inheritance from the app_callback_class
class user_app_callback_class(app_callback_class):
    def __init__(self):
        super().__init__()

# User-defined callback function: This is the callback function that will be called when data is available from the pipeline
def app_callback(pad, info, user_data):
    save_frames_per_frame = 1 # save x frames out of y frames
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
    # Save frame as JPEG (every 5th frame to save space)
    if not hasattr(app_callback, 'count'):
        app_callback.count = 0
    app_callback.count += 1

    if app_callback.count % save_frames_per_frame == 0:
        success, map_info = buffer.map(Gst.MapFlags.READ)
        if success:
            try:
                frame_queue.put_nowait((time.time_ns(), bytes(map_info.data), width, height))
            except queue_module.Full:
                pass
            buffer.unmap(map_info)
    return Gst.PadProbeReturn.OK

def make_ai_app():
    import sys
    project_root = Path(__file__).resolve().parent.parent
    env_file     = project_root / ".env"
    env_path_str = str(env_file)
    os.environ["HAILO_ENV_FILE"] = env_path_str
    # Force RPi camera input so we don't need to pass -i rpi on the command line
    if "-i" not in sys.argv and "--input" not in sys.argv:
        sys.argv += ["-i", "rpi"]
    if "--hef-path" not in sys.argv:
        sys.argv += ["--hef-path", "/usr/local/hailo/resources/models/hailo8/yolov8m.hef"]
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
             
