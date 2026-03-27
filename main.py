import sys


def main():
    is_sim = "-s" in sys.argv or "--sim" in sys.argv

    if is_sim:
        speed = int(float(sys.argv[sys.argv.index("--speed") + 1])) if "--speed" in sys.argv else 1
        from sitl import launch_sitl_process
        sitl_proc = launch_sitl_process(speed)

    # Imports that connect to the drone must happen after SITL is running
    from ai_class import ai_storage_singleton
    from telemetry import telemetry_singlton
    from DB_abstraction import db_abstraction, Waypoint
    from fsm import StateMachine
    from mission_logging import init_mission_log, allocate_mission_dir, configure_mission_dir
    from constants import MIN_SPRAY_ERROR
    from pathlib import Path

    if is_sim:
        from sitl import (disable_sensor_noise, set_sim_speed, setup_rangefinder,
                          arm_and_takeoff, get_sim_files, load_sim_file)
        import constants
        import time

        conn = telemetry_singlton.connection
        disable_sensor_noise(conn)
        set_sim_speed(conn, speed)
        setup_rangefinder(conn)
        time.sleep(0.5)
        arm_and_takeoff(conn, telemetry_singlton)

        for file in get_sim_files():
            configure_mission_dir(allocate_mission_dir(Path(__file__).resolve().parent))
            init_mission_log(is_sim=True, sim_truth_file=file, weed_match_m=0.5, min_spray_error_m=float(MIN_SPRAY_ERROR))
            load_sim_file(file)
            fsm = StateMachine()
            while fsm.update() is not False:
                time.sleep((1 / 30) / constants.SIM_SPEED)

        sitl_proc.terminate()
        return

    print("you are about to fly do your prflight checks")
    print("press r to resume")
    print("press n for a new mission from the currently saved auto mission")
    print("press c to cancel and ctrl + c should also stop it at any time mabey")
    print("w just uplod a weed location this is where home is")

    inp = input("press r/n/c/w ")

    if inp == "n":
        wps_new = []
        id = 0
        for i in telemetry_singlton.get_auto_mission_wp():
            wp = Waypoint(*i, id=id)
            wps_new.append(wp)
            id += 1
        db_abstraction.backup_and_clear()
        for i in wps_new:
            db_abstraction.add_waypoint(i)

    elif inp == "r":
        pass

    elif inp == "w":
        print("the drone suould be a weed")
        input("press enter when done")
        db_abstraction.backup_and_clear()
        lon, lat = telemetry_singlton.drone_state.longitude, telemetry_singlton.drone_state.latitude
        db_abstraction.add_waypoint(Waypoint(lon=lon, lat=lat))

    else:
        return

    if input("type y when taken off (y) ") != "y":
        return

    configure_mission_dir(allocate_mission_dir(Path(__file__).resolve().parent))
    init_mission_log(
        is_sim=False,
        weed_match_m=0.5,
        min_spray_error_m=float(MIN_SPRAY_ERROR),
    )
    ai_storage_singleton.start_ai()
    fsm = StateMachine()

    while True:
        fsm.update()


if __name__ == "__main__":
    main()
