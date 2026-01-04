#!/usr/bin/env python3
"""Test hailo wrapper imports step by step."""

print("Step 1: Testing basic imports...")
try:
    from hailo_wrapper import GStreamerDetectionApp, user_app_callback_class
    print("✓ Basic imports successful")
except Exception as e:
    print(f"✗ Basic imports failed: {e}")
    exit(1)

print("\nStep 2: Testing GStreamer init...")
try:
    from gi.repository import Gst
    Gst.init(None)
    print(f"✓ GStreamer initialized: {Gst.version_string()}")
except Exception as e:
    print(f"✗ GStreamer init failed: {e}")
    exit(1)

print("\nStep 3: Creating user_data...")
try:
    user_data = user_app_callback_class()
    print(f"✓ user_data created: frame_count={user_data.frame_count}")
except Exception as e:
    print(f"✗ user_data creation failed: {e}")
    exit(1)

print("\nStep 4: Creating callback...")
def test_callback(pad, info, user_data):
    return Gst.PadProbeReturn.OK

print("✓ Callback defined")

print("\nStep 5: Creating GStreamerDetectionApp (this might crash)...")
try:
    app = GStreamerDetectionApp(test_callback, user_data)
    print("✓ GStreamerDetectionApp created!")
except Exception as e:
    print(f"✗ GStreamerDetectionApp creation failed: {e}")
    import traceback
    traceback.print_exc()
    exit(1)

print("\n✅ All tests passed! App ready to run.")
print("Note: We didn't call app.run() - that would start the pipeline.")
