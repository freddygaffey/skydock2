import sys
import os
import time
import json
import argparse


def _ask_for_mission(telemetry_singlton):
    from mission_gen import save_mission

    # List existing mission files
    existing = sorted(f for f in os.listdir("real_missions") if f.endswith(".json")) if os.path.isdir("real_missions") else []
    if existing:
        print("existing missions:")
        for i, f in enumerate(existing, 1):
            print(f"  {i}. {f}")

    raw = input("enter mission file name or number: ").strip()

    # If user entered a number, resolve to filename
    if raw.isdigit():
        idx = int(raw) - 1
        if 0 <= idx < len(existing):
            file_name = existing[idx]
        else:
            print("invalid number")
            return None
    else:
        file_name = raw
        if not file_name.endswith(".json"):
            file_name += ".json"

    path = f"real_missions/{file_name}"

    if os.path.exists(path):
        print("that file exists")
        input("take off the drone and press enter")
        return path
    else:
        if input("make a new file? press y: ").lower() != "y":
            return None
        print("waiting for GPS fix...")
        while telemetry_singlton.drone_state.latitude == 0 and telemetry_singlton.drone_state.longitude == 0:
            time.sleep(0.1)
        print("GPS fix acquired")
        print("move the drone above each weed and press enter, type 'f' when done q to cancel")
        weeds = []
        while True:
            i = input("> ").strip()
            if i.lower() == "f":
                break
            if i.lower() == "q":
                return None
            lat = telemetry_singlton.drone_state.latitude
            lon = telemetry_singlton.drone_state.longitude
            weeds.append({"id": len(weeds), "lat": lat, "lon": lon})
            print(f"  weed {len(weeds)} at ({lat:.6f}, {lon:.6f})")
        if not weeds:
            print("no weeds recorded")
            return None
        os.makedirs("real_missions", exist_ok=True)
        return save_mission(weeds, name=file_name.replace(".json", ""), out_dir="real_missions")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sim", "-s", action="store_true")
    parser.add_argument("--speed", "--speedup", type=float, default=1.0)
    args, _ = parser.parse_known_args()
    is_sim = args.sim
    speed = int(args.speed)

    # Start SITL before connecting telemetry
    if is_sim:
        from sitl import start_sim
        start_sim(speed)
        connection_string = "udp:127.0.0.1:14550"
    else:
        connection_string = None

    # Imports that connect to the drone must happen after SITL is running
    import telemetry
    from telemetry import Telemetry
    telemetry.telemetry_singlton = Telemetry(connection_string=connection_string)
    telemetry_singlton = telemetry.telemetry_singlton

    from mission_logging import allocate_mission_dir, configure_mission_dir, init_mission_log, log_event
    from pathlib import Path
    from DB import set_db_path

    # set_db_path must be called before fsm is imported (which triggers db_abstraction init)
    mission_dir = allocate_mission_dir(Path(__file__).resolve().parent)
    set_db_path(str(mission_dir / "droneDB.db"))
    configure_mission_dir(mission_dir)

    # Select mission file BEFORE importing FSM so constants can be set from JSON
    if is_sim:
        from sitl import get_sim_files
        mission_file = get_sim_files()[0]
    else:
        mission_file = _ask_for_mission(telemetry_singlton)
        if mission_file is None:
            return

    # Load params from mission JSON and set constants before FSM/state modules are imported
    mission_path = mission_file if os.path.exists(mission_file) else f"sim_data/{mission_file}"
    with open(mission_path) as f:
        _mission_data = json.load(f)

    if _mission_data.get("is_sim") and not is_sim:
        from utils import haversine_distance
        drone = telemetry_singlton.drone_state
        print(f"\n[WARNING] '{os.path.basename(mission_file)}' is a sim file!")
        print("Weed distances from drone:")
        for w in _mission_data.get("weed_locations", []):
            dist_m = haversine_distance(drone.latitude, drone.longitude, w["lat"], w["lon"])
            print(f"  weed {w['id']}: {dist_m/1000:.1f} km away")
        if input("Continue anyway? (y to confirm): ").strip().lower() != "y":
            return

    params = _mission_data["params"]

    import constants
    constants.SCAN_HIGHT             = float(params["scan_height_m"])
    constants.SCAN_SPEED_MS          = float(params["scan_speed_ms"])
    constants.MIN_DIST_FROM_WAYPOINT = float(params["min_dist_from_waypoint_m"])
    constants.MIN_WEED_SPACING       = float(params["min_weed_spacing_m"])
    constants.MIN_NUM_DET            = int(params["min_num_det"])
    constants.GOTO_ALT               = float(params["goto_alt_m"])
    constants.MAX_HOMING_DIST        = float(params["max_homing_dist_m"])
    constants.MIN_ALT                = float(params["min_alt_m"])
    constants.MAX_HOMING_ALT         = float(params["max_homing_alt_m"])
    constants.MIN_SPRAY_ERROR        = float(params["min_spray_error_m"])
    constants.TIME_WAIT_FOR_DET      = float(params["time_wait_for_det_s"])
    constants.MAX_HOMING_TIME        = float(params["max_homing_time_s"])

    constants.SIM_AI_ENABLE_IMPERFECTIONS = (
        bool(params.get("sim_ai_enable_imperfections", False)) if is_sim else False
    )

    # Now import FSM — state modules will capture the correct values from constants
    from ai_class import ai_storage_singleton
    from fsm import StateMachine

    # Init mission log
    truth_file = mission_file if is_sim else os.path.basename(mission_file)
    init_mission_log(is_sim=is_sim, truth_file=truth_file, weed_match_m=0.5, min_spray_error_m=float(constants.MIN_SPRAY_ERROR))

    # Pre-flight
    if is_sim:
        from sitl import set_sim_speed, setup_rangefinder, arm_and_takeoff, enable_sim_rc
        conn = telemetry_singlton.connection
        set_sim_speed(conn, speed)
        setup_rangefinder(conn)
        enable_sim_rc(conn)
        time.sleep(0.5)
        if not arm_and_takeoff(conn, telemetry_singlton, speed=speed):
            print("[main] arm/takeoff failed, aborting")
            from sitl import kill_sim
            kill_sim()
            return
    else:
        input("please press enter after takeoff")

    # Load mission and start AI
    from sitl import load_mission_file
    mission = load_mission_file(mission_file, start_sim_ai=is_sim)
    log_event("mission_plan", logger="main", level="INFO", mission=mission)

    if not is_sim:
        ai_storage_singleton.start_sim_ai(None)

    # FSM loop (~30 Hz; SIM_SPEED=1 on real hardware)
    fsm = StateMachine()
    try:
        while fsm.update() is not False:
            time.sleep((1 / 30) / constants.SIM_SPEED)
    except KeyboardInterrupt:
        pass
    finally:
        if is_sim:
            from sitl import kill_sim
            kill_sim()


if __name__ == "__main__":
    main()
