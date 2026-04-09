import sys
import os
import time

def main():
    is_sim = "-s" in sys.argv or "--sim" in sys.argv

    speed = int(float(sys.argv[sys.argv.index("--speedup") + 1])) if "--speedup" in sys.argv else (int(float(sys.argv[sys.argv.index("--speed") + 1])) if "--speed" in sys.argv else 1)

    if is_sim:
        from sitl import slot_port, get_sim_files,start_sim, SLOT_BASE_PORT, SLOT_PORT_STEP
        import subprocess

        if "--sim-port" not in sys.argv:
            # top-level invocation: launch one subprocess per sim file
            sim_files = get_sim_files()
            start_sim(speed, count=len(sim_files))
            if len(sim_files) > 1:
                children = []
                for slot, f in enumerate(sim_files):
                    port = slot_port(slot)
                    # essenaliy calling recucivly
                    cmd = (
                        f"{sys.executable} main.py --sim '{f}' --sim-port {port} --speedup {speed}; "
                        f"echo 'Done - press enter to close'; read"
                    )
                    children.append(subprocess.Popen(
                        ["xterm", "-title", f"Vehicle {slot} - {f}", "-e", "bash", "-c", cmd]
                    ))
                try:
                    for c in children:
                        c.wait()
                except KeyboardInterrupt:
                    for c in children:
                        c.terminate()
                    from sitl import kill_sim
                    kill_sim()
                return

        sim_port = int(sys.argv[sys.argv.index("--sim-port") + 1]) if "--sim-port" in sys.argv else 14552
        slot = (sim_port - SLOT_BASE_PORT) // SLOT_PORT_STEP

        connection_string = f"udp:127.0.0.1:{sim_port}"
    else:
        connection_string = None

    # Imports that connect to the drone must happen after SITL is running
    import telemetry
    from telemetry import Telemetry
    sysid = slot + 1 if is_sim else None
    telemetry.telemetry_singlton = Telemetry(connection_string=connection_string, sysid=sysid)
    telemetry_singlton = telemetry.telemetry_singlton

    from mission_logging import init_mission_log, allocate_mission_dir, configure_mission_dir
    from constants import MIN_SPRAY_ERROR
    from pathlib import Path
    from mission_logging import log_event
    from DB import set_db_path

    # set_db_path must be called before fsm is imported (which triggers db_abstraction init)
    mission_dir = allocate_mission_dir(Path(__file__).resolve().parent)
    set_db_path(str(mission_dir / "droneDB.db"))
    configure_mission_dir(mission_dir)

    from ai_class import ai_storage_singleton
    from fsm import StateMachine

    if is_sim:
        from sitl import (set_sim_speed, setup_rangefinder,
                          arm_and_takeoff, get_sim_files,
                          load_mission_file, enable_sim_rc, kill_sim)
        import constants
        import time
        conn = telemetry_singlton.connection

        sim_files = get_sim_files()
        file = sim_files[slot] if slot < len(sim_files) else sim_files[0]
        init_mission_log(is_sim=True, truth_file=file, weed_match_m=0.5, min_spray_error_m=float(MIN_SPRAY_ERROR))

        set_sim_speed(conn, speed)
        setup_rangefinder(conn)
        enable_sim_rc(conn)
        time.sleep(0.5)
        arm_and_takeoff(conn, telemetry_singlton, speed=speed)

        load_mission_file(file)
        fsm = StateMachine()
        try:
            while fsm.update() is not False:
                time.sleep((1 / 30) / constants.SIM_SPEED)
        except KeyboardInterrupt:
            pass
        finally:
            kill_sim()
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
        truth_basename = os.path.basename(mission_path)
        init_mission_log(
            is_sim=False,
            truth_file=truth_basename,
            weed_match_m=0.5,
            min_spray_error_m=float(MIN_SPRAY_ERROR),
        )
        mission = load_mission_file(mission_path, start_sim_ai=False)
        log_event("mission_plan", logger="main", level="INFO", mission=mission)

        input("please press enter after takeoff")

        ai_storage_singleton.start_sim_ai(None)
        fsm = StateMachine()

        while True:
            fsm.update()

if __name__ == "__main__":
    main()
