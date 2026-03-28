#!/usr/bin/env python3
"""
SKYDOCK PRE-FLIGHT TEST SUITE
Run this before every flight session to catch issues early.

Usage:
    python preflight_tests.py          # Run all tests
    python preflight_tests.py --no-ai  # Skip AI tests (faster, no camera needed)
"""

import sys
import time
import argparse
import math

# Test results tracking
class TestResults:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.warnings = 0
        self.errors = []

    def ok(self, msg):
        self.passed += 1
        print(f"  ✓ {msg}")

    def fail(self, msg):
        self.failed += 1
        self.errors.append(msg)
        print(f"  ✗ {msg}")

    def warn(self, msg):
        self.warnings += 1
        print(f"  ⚠ {msg}")

    def summary(self):
        total = self.passed + self.failed
        print(f"\n{'='*50}")
        if self.failed == 0:
            print(f"ALL TESTS PASSED ({self.passed}/{total})")
            if self.warnings > 0:
                print(f"  {self.warnings} warning(s) - review above")
            print("READY FOR FLIGHT")
        else:
            print(f"TESTS FAILED ({self.failed} failed, {self.passed} passed)")
            print("DO NOT FLY - Fix issues first:")
            for err in self.errors:
                print(f"  - {err}")
        print(f"{'='*50}")
        return self.failed == 0


def test_telemetry_connection(results: TestResults):
    """Test MAVLink connection and data reception"""
    print("\n[1/6] TELEMETRY CONNECTION")

    try:
        from telemetry import telemetry_singlton
    except Exception as e:
        results.fail(f"Cannot import telemetry: {e}")
        return None

    results.ok("Telemetry module imported")

    # Wait for data to flow in
    print("  Waiting for telemetry data...")
    time.sleep(2)

    state = telemetry_singlton.drone_state
    return state


def test_gps_fix(results: TestResults, state):
    """Test GPS has a valid fix with detailed quality diagnostics"""
    print("\n[2/6] GPS FIX")

    if state is None:
        results.fail("No drone state available")
        return

    # --- Data freshness (time_updated is boot-time seconds, so sample twice) ---
    if state.time_updated_GLOBAL_POSITION_INT == 0:
        results.fail("No GLOBAL_POSITION_INT message received yet")
        return
    t1 = state.time_updated_GLOBAL_POSITION_INT
    time.sleep(0.3)
    t2 = state.time_updated_GLOBAL_POSITION_INT
    if t1 == t2:
        results.warn("GPS data has stopped updating - telemetry may be lagging")
    else:
        results.ok("GPS data is updating")

    # --- Position ---
    if state.latitude == 0 and state.longitude == 0:
        results.fail("Position is 0,0 - no valid position fix")
        return
    results.ok(f"Position: {state.latitude:.7f}, {state.longitude:.7f}")

    # --- Altitude ---
    if state.altitude_rel_home == 0:
        results.warn("Altitude relative to home is 0 (normal on ground before arming)")
    else:
        results.ok(f"Altitude: {state.altitude_rel_home:.1f}m (rel home)")

    # --- Heading ---
    if state.heading is None:
        results.fail("Heading unknown (hdg=65535) - compass may not be calibrated")
    elif state.heading == 0:
        results.warn("Heading is 0° - could be north or compass not ready")
    else:
        results.ok(f"Heading: {state.heading:.1f}°")

    # --- Ground speed (should be near zero on ground) ---
    speed = math.sqrt(state.velocity_x**2 + state.velocity_y**2)
    if speed > 1.0:
        results.warn(f"Ground speed {speed:.1f} m/s - drone should be stationary")
    else:
        results.ok(f"Ground speed: {speed:.2f} m/s (stationary)")


def test_flight_mode(results: TestResults, state):
    """Test flight mode and arm state"""
    print("\n[3/6] FLIGHT MODE")

    if state is None:
        results.fail("No drone state available")
        return

    mode = state.mode
    if mode is None:
        results.fail("No mode data received")
        return

    results.ok(f"Current mode: {mode}")

    # Check arm state
    from telemetry import telemetry_singlton
    armed = telemetry_singlton.arm_state
    if armed:
        results.warn("Drone is ARMED - be careful!")
    else:
        results.ok("Drone is disarmed")

    # Autonomy switch
    autonomy = state.enable_homing_and_autonomy
    print(f"  Autonomy switch: {'ENABLED' if autonomy else 'DISABLED'}")
    if autonomy:
        results.warn("Autonomy is ENABLED - disable before flight prep")
    else:
        results.ok("Autonomy switch disabled (safe)")


def test_attitude_data(results: TestResults, state):
    """Test attitude (roll/pitch/yaw) data reception"""
    print("\n[4/6] ATTITUDE DATA")

    if state is None:
        results.fail("No drone state available")
        return

    roll = math.degrees(state.rotaion.x)
    pitch = math.degrees(state.rotaion.y)
    yaw = math.degrees(state.rotaion.z)

    results.ok(f"Roll: {roll:.1f}°, Pitch: {pitch:.1f}°, Yaw: {yaw:.1f}°")

    # Sanity check - drone should be roughly level on ground
    if abs(roll) > 15:
        results.warn(f"Roll angle is large ({roll:.1f}°) - is drone level?")
    if abs(pitch) > 15:
        results.warn(f"Pitch angle is large ({pitch:.1f}°) - is drone level?")


def test_ai_pipeline(results: TestResults):
    """Test AI pipeline is running and producing frames with bounding boxes"""
    print("\n[5/6] AI PIPELINE")

    try:
        from ai_class import ai_storage_singleton
    except Exception as e:
        results.fail(f"Cannot import ai_class: {e}")
        return

    results.ok("ai_class imported")

    # Start AI using the singleton's start_ai method
    print("  Starting AI via ai_storage_singleton.start_sim_ai()...")
    try:
        ai_storage_singleton.start_sim_ai()
    except Exception as e:
        results.fail(f"Failed to start AI: {e}")
        return

    results.ok("AI started")

    # Poll for frames with detections (bounding boxes)
    print("  Polling for frames with bounding boxes...")
    max_attempts = 10
    frames_received = 0
    detections_found = 0
    bbox_valid = False

    for attempt in range(max_attempts):
        time.sleep(0.5)
        frame = ai_storage_singleton.get_latest_frame()

        if frame is not None:
            frames_received += 1

            # Check if we have detections with bounding boxes
            for det in frame.detection:
                detections_found += 1
                # Validate bbox format: list of tuples [(x1,y1), (x2,y2)]
                if det.bbox and len(det.bbox) >= 2:
                    x1, y1 = det.bbox[0]
                    x2, y2 = det.bbox[1]
                    # Check bbox values are normalized (0-1) or pixel coords
                    if x1 != x2 and y1 != y2:
                        bbox_valid = True
                        print(f"      Detection: {det.label} conf={det.confidence:.2f}")
                        print(f"        bbox: ({x1:.3f},{y1:.3f}) -> ({x2:.3f},{y2:.3f})")

        if bbox_valid:
            break

    # Report results
    if frames_received == 0:
        results.fail("No frames received from AI pipeline")
        return

    results.ok(f"Frames received: {frames_received}/{max_attempts} polls")

    if detections_found > 0:
        results.ok(f"Total detections found: {detections_found}")
        if bbox_valid:
            results.ok("Bounding boxes are valid")
        else:
            results.warn("Detections found but bbox format looks wrong")
    else:
        results.warn("No detections yet - point camera at a test object (ball/frisbee/person)")


def test_database(results: TestResults):
    """Test database connection and data integrity"""
    print("\n[6/6] DATABASE")

    try:
        from DB_abstraction import DBAbstraction
    except Exception as e:
        results.fail(f"Cannot import database: {e}")
        return

    try:
        db = DBAbstraction()
    except Exception as e:
        results.fail(f"Cannot connect to database: {e}")
        return

    results.ok("Database connected")

    # Get stats
    try:
        stats = db.get_stats()
        results.ok(f"Waypoints: {stats['total_waypoints']} ({stats['traveled_waypoints']} visited)")
        results.ok(f"Weeds: {stats['total_weeds']} ({stats['sprayed_weeds']} sprayed)")

        if stats['total_waypoints'] == 0:
            results.warn("No waypoints loaded - load mission before flight")
    except Exception as e:
        results.fail(f"Database query failed: {e}")


def test_coordinate_transform(results: TestResults):
    """Test camera-to-world coordinate transformation math"""
    print("\n[BONUS] COORDINATE TRANSFORM")

    try:
        from utils import detection_to_ned
        from ai_class import Detection
        from drone_state import DroneStateForHoming
    except Exception as e:
        results.fail(f"Cannot import utils: {e}")
        return

    # Create a fake detection in center of frame (pixel coords, 640x640)
    fake_det = Detection(
        label="test",
        confidence=1.0,
        bbox=[(310, 310), (330, 330)]  # center of 640x640 frame
    )

    # Create a mock drone state - level at 15m altitude
    mock_state = DroneStateForHoming()
    mock_state.altitude_rel_home = 15.0
    mock_state.rotaion.x = 0   # roll
    mock_state.rotaion.y = 0   # pitch
    mock_state.rotaion.z = 0   # yaw
    mock_state.rotaion.dx = 0  # roll rate
    mock_state.rotaion.dy = 0  # pitch rate
    mock_state.rotaion.dz = 0  # yaw rate

    try:
        ned = detection_to_ned(mock_state, fake_det)

        # Center detection should be nearly straight down (small N/E offset)
        if abs(ned[0]) < 5 and abs(ned[1]) < 5:
            results.ok(f"NED transform OK: N={ned[0]:.2f}m, E={ned[1]:.2f}m")
        else:
            results.warn(f"NED offset larger than expected: N={ned[0]:.2f}, E={ned[1]:.2f}")
    except Exception as e:
        results.fail(f"Transform calculation failed: {e}")


def main():
    parser = argparse.ArgumentParser(description="Skydock Pre-Flight Tests")
    parser.add_argument("--no-ai", action="store_true", help="Skip AI pipeline tests")
    parser.add_argument("--quick", action="store_true", help="Quick mode - minimal waits")
    args = parser.parse_args()

    results = TestResults()

    # Start AI first so camera noise appears before any test output
    if not args.no_ai:
        test_ai_pipeline(results)
    else:
        print("\n[5/6] AI PIPELINE - SKIPPED")

    print("="*50)
    print("SKYDOCK PRE-FLIGHT TEST SUITE")
    print("="*50)

    # Test 1: Telemetry connection
    state = test_telemetry_connection(results)

    # Test 2: GPS fix
    test_gps_fix(results, state)

    # Test 3: Flight mode
    test_flight_mode(results, state)

    # Test 4: Attitude data
    test_attitude_data(results, state)

    # Test 6: Database
    test_database(results)

    # Bonus: Coordinate transform
    test_coordinate_transform(results)

    # Summary
    success = results.summary()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
