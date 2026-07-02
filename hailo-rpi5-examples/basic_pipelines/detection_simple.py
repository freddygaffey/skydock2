# from ai_class import ai_storage, Frame, Detection
from ai_class import ai_storage_singleton, Detection, Frame
from mission_logging import get_mission_dir
import telemetry  # lazy: telemetry.telemetry_singlton set by main.py at runtime

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

from constants import TARGET_FPS  # shared with sim_ai so sim and real run the same frame rate
SAVE_EVERY_N_FRAMES = 2  # save every 2nd frame as jpg

# Frame saving queue
frame_queue = queue_module.Queue(maxsize=500)


# Hailo's bundled picamera_thread hardcodes FrameRate=30. Patch it before app starts so the
# Picamera2 lores stream and downstream caps both run at TARGET_FPS.
def _patched_picamera_thread(pipeline, video_width, video_height, video_format, picamera_config=None):
    from picamera2 import Picamera2
    appsrc = pipeline.get_by_name("app_source")
    appsrc.set_property("is-live", True)
    appsrc.set_property("format", Gst.Format.TIME)
    with Picamera2() as picam2:
        if picamera_config is None:
            main = {"size": (1280, 720), "format": "RGB888"}
            lores = {"size": (video_width, video_height), "format": "RGB888"}
            controls = {"FrameRate": TARGET_FPS}
            config = picam2.create_preview_configuration(main=main, lores=lores, controls=controls)
        else:
            config = picamera_config
        picam2.configure(config)
        lores_stream = config["lores"]
        format_str = "RGB" if lores_stream["format"] == "RGB888" else video_format
        width, height = lores_stream["size"]
        appsrc.set_property("caps", Gst.Caps.from_string(
            f"video/x-raw, format={format_str}, width={width}, height={height}, framerate={TARGET_FPS}/1, pixel-aspect-ratio=1/1"
        ))
        picam2.start()
        frame_count = 0
        while True:
            frame_data = picam2.capture_array("lores")
            if frame_data is None:
                break
            frame = cv2.cvtColor(frame_data, cv2.COLOR_BGR2RGB)
            buffer = Gst.Buffer.new_wrapped(frame.tobytes())
            buffer_duration = Gst.util_uint64_scale_int(1, Gst.SECOND, TARGET_FPS)
            buffer.pts = frame_count * buffer_duration
            buffer.duration = buffer_duration
            ret = appsrc.emit("push-buffer", buffer)
            if ret == Gst.FlowReturn.FLUSHING or ret != Gst.FlowReturn.OK:
                break
            frame_count += 1


import hailo_apps.hailo_app_python.core.gstreamer.gstreamer_app as _hga
_hga.picamera_thread = _patched_picamera_thread

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

            # the time_ns.jpg
            cv2.imwrite(str(frames_dir / f"{timestamp_ns}.jpg"), frame)

            # frame latest this will get overwritten 
            # this is a atomic write
            out_path = frames_dir / "tmp_latest.jpg"
            cv2.imwrite(str(out_path), frame)
            os.replace(f"{frames_dir}/tmp_latest.jpg",f"{frames_dir}/latest.jpg")
            # cv2.imwrite(str(frames_dir / "latest.jpg"), frame)

        except queue_module.Empty:
            continue

# Start the saver thread
threading.Thread(target=frame_saver_thread, daemon=True).start()

# User-defined class to be used in the callback function: Inheritance from the app_callback_class
class user_app_callback_class(app_callback_class):
    def __init__(self):
        super().__init__()

# User-defined callback function: This is the callback function that will be called when data is available from the pipeline
_det_print_last = 0
_det_print_count = 0

def app_callback(pad, info, user_data):
    global _det_print_last, _det_print_count
    save_frames_per_frame = SAVE_EVERY_N_FRAMES
    buffer = info.get_buffer()  # Get the GstBuffer from the probe info
    if buffer is None:  # Check if the buffer is valid
        return Gst.PadProbeReturn.OK

    caps = pad.get_current_caps()
    structure = caps.get_structure(0)
    width = structure.get_value('width')
    height = structure.get_value('height')

    # Capture wall-clock time = now - (pipeline_now - buffer.pts). buffer.pts is in
    # pipeline clock ns at sensor capture; subtracting from current pipeline clock
    # gives buffer age, then offset from time.time_ns() recovers true capture time.
    capture_time_ns = time.time_ns()
    if buffer.pts != Gst.CLOCK_TIME_NONE:
        elem = pad.get_parent_element()
        clock = elem.get_clock() if elem is not None else None
        if clock is not None:
            pipeline_now = clock.get_time()
            if pipeline_now != Gst.CLOCK_TIME_NONE and pipeline_now >= buffer.pts:
                capture_time_ns = time.time_ns() - (pipeline_now - buffer.pts)

    frame = Frame([])
    ts = getattr(telemetry, "telemetry_singlton", None)
    if ts is not None:
        ts.drone_state.width = width
        ts.drone_state.height = height
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
        det = Detection(label=label,confidence=confidence,bbox=bbox,time_ns=capture_time_ns)
        if "ball" in det.label:
            _det_print_count += 1
        frame.add_detection(det)

    ai_storage_singleton.set_latest_frame(frame)
    now = time.time()
    if _det_print_count and now - _det_print_last >= 5:
        print(f"DET {_det_print_count} found")
        _det_print_count = 0
        _det_print_last = now
    # Save frame as JPEG (every 5th frame to save space)
    if not hasattr(app_callback, 'count'):
        app_callback.count = 0
    app_callback.count += 1

    if app_callback.count % save_frames_per_frame == 0:
        success, map_info = buffer.map(Gst.MapFlags.READ)
        if success:
            try:
                frame_queue.put_nowait((capture_time_ns, bytes(map_info.data), width, height))
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
        sys.argv += ["--hef-path", "/home/fred/skydock2/models/ball_detection.hef"]
    if "--labels-json" not in sys.argv:
        sys.argv += ["--labels-json", "/home/fred/skydock2/models/ball_labels.json"]
    if "--frame-rate" not in sys.argv and "-r" not in sys.argv:
        sys.argv += ["--frame-rate", str(TARGET_FPS)]
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
             
