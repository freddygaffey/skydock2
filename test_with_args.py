#!/usr/bin/env python3
"""Test hailo detection with proper arguments."""

import sys
import argparse
from hailo_wrapper import GStreamerDetectionApp, user_app_callback_class, get_detections_from_buffer
from gi.repository import Gst

def my_callback(pad, info, user_data):
    """Simple callback that just counts detections."""
    buffer = info.get_buffer()
    detections = get_detections_from_buffer(buffer)

    if detections:
        print(f"Frame {user_data.get_count()}: {len(detections)} detections")
        for det in detections:
            label = det.get_label()
            conf = det.get_confidence()
            print(f"  - {label}: {conf:.2f}")

    user_data.increment()
    return Gst.PadProbeReturn.OK

# Create argument parser
parser = argparse.ArgumentParser(description="Hailo Detection Test")
parser.add_argument("--input", "-i", type=str, default="rpi",
                    help="Input source (rpi, usb, /dev/video0, or video file)")
parser.add_argument("--show-fps", action="store_true", help="Show FPS")

print("Creating user_data...")
user_data = user_app_callback_class()

print("Creating GStreamerDetectionApp with parser...")
print("This will use default hailo model and camera input")
try:
    app = GStreamerDetectionApp(my_callback, user_data, parser=parser)
    print("✓ App created successfully!")
    print("\nStarting pipeline...")
    print("Press Ctrl+C to stop\n")
    app.run()
except KeyboardInterrupt:
    print("\n\nStopped by user")
except Exception as e:
    print(f"\n✗ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
