import sys
import os

def main():
    is_sim = "-s" in sys.argv or "--sim" in sys.argv

    if is_sim:
        speed = int(float(sys.argv[sys.argv.index("--speed") + 1])) if "--speed" in sys.argv else 1
        from sitl import launch_sitl_process
        sitl_proc = launch_sitl_process(speed)

    # Imports that connect to the drone must happen after SITL is running
    from ai_class import ai_storage_singleton
    from telemetry import telemetry_singlton
    from fsm import StateMachine
    from mission_logging import init_mission_log, allocate_mission_dir, configure_mission_dir
    from constants import MIN_SPRAY_ERROR
    from pathlib import Path
    from mission_logging import log_event

    if is_sim:
        from sitl import (disable_sensor_noise, set_sim_speed, setup_rangefinder,
                          arm_and_takeoff, get_sim_files, load_mission_file)
        import constants
        import time

        conn = telemetry_singlton.connection
        # disable_sensor_noise(conn)
        set_sim_speed(conn, speed)
        setup_rangefinder(conn)
        time.sleep(0.5)
        arm_and_takeoff(conn, telemetry_singlton)

        for file in get_sim_files():
            configure_mission_dir(allocate_mission_dir(Path(__file__).resolve().parent))
            init_mission_log(is_sim=True, truth_file=file, weed_match_m=0.5, min_spray_error_m=float(MIN_SPRAY_ERROR))
            load_mission_file(file)
            fsm = StateMachine()
            while fsm.update() is not False:
                time.sleep((1 / 30) / constants.SIM_SPEED)

        sitl_proc.terminate()
        return
    else:
        def ask():
            from mission_gen import save_mission
            file_name = input("enter mission file name: ").strip()
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
                import time
                print("waiting for GPS fix...")
                while telemetry_singlton.drone_state.latitude == 0 and telemetry_singlton.drone_state.longitude == 0:
                    time.sleep(0.1)
                print("GPS fix acquired")
                print("move the drone above each weed and press enter, type 'f' when done q to can")
                weeds = []
                while True:
                    i = input("> ").strip()
                    if i.lower() == "f":
                        break
                    if i.lower() == "q": return
                    lat = telemetry_singlton.drone_state.latitude
                    lon = telemetry_singlton.drone_state.longitude
                    weeds.append({"id": len(weeds), "lat": lat, "lon": lon})
                    print(f"  weed {len(weeds)} at ({lat:.6f}, {lon:.6f})")
                if not weeds:
                    print("no weeds recorded")
                    return None
                os.makedirs("real_missions", exist_ok=True)
                return save_mission(weeds, name=file_name.replace(".json", ""), out_dir="real_missions")

        mission_path = ask()
        if mission_path is None:
            return

        from sitl import load_mission_file
        configure_mission_dir(allocate_mission_dir(Path(__file__).resolve().parent))
        init_mission_log(is_sim=False, weed_match_m=0.5, min_spray_error_m=float(MIN_SPRAY_ERROR))
        mission = load_mission_file(mission_path, start_sim_ai=False)
        log_event("mission_plan", logger="main", level="INFO", mission=mission)

        input("please press enter after takeoff")

        ai_storage_singleton.start_sim_ai()
        fsm = StateMachine()

        while True:
            fsm.update()

if __name__ == "__main__":
    main()
