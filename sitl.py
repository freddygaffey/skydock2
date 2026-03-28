import os
import sys
import json
import time
import subprocess


from pymavlink import mavutil


def set_param(conn, name: bytes, value: float):
    conn.mav.param_set_send(
        conn.target_system, conn.target_component,
        name, value, mavutil.mavlink.MAV_PARAM_TYPE_REAL32
    )


def disable_sensor_noise(conn):
    print("[sitl] disabling sensor noise...")
    for name in [b"SIM_GYRO_RND", b"SIM_ACC_RND", b"SIM_MAG_RND", b"SIM_BARO_RND", b"SIM_GPS_NOISE"]:
        set_param(conn, name, 0.0)


def set_sim_speed(conn, speed: float):
    print(f"[sitl] setting sim speedup to {speed}x...")
    set_param(conn, b"SIM_SPEEDUP", speed)


def setup_rangefinder(conn):
    print("[sitl] configuring simulated rangefinder...")
    set_param(conn, b"RNGFND1_TYPE",    100.0)  # SITL simulated
    set_param(conn, b"RNGFND1_ORIENT",   25.0)  # MAV_SENSOR_ROTATION_PITCH_270 = nadir
    set_param(conn, b"RNGFND1_MAX_CM", 5000.0)  # 50 m
    set_param(conn, b"RNGFND1_MIN_CM",   20.0)  # 0.2 m


def arm_and_takeoff(conn, telemetry, altitude: float = 10):
    print("[sitl] waiting for EKF and GPS to be ready (retrying arm)...")
    for i in range(30):
        print(f"lunch atempt {i}/30")
        conn.mav.command_long_send(
            conn.target_system, conn.target_component,
            mavutil.mavlink.MAV_CMD_DO_SET_MODE, 0,
            1, 4, 0, 0, 0, 0, 0  # 4 = GUIDED
        )
        time.sleep(1)
        conn.mav.command_long_send(
            conn.target_system, conn.target_component,
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0,
            1, 21196, 0, 0, 0, 0, 0  # 21196 = force arm
        )
        time.sleep(2)
        if telemetry.arm_state:
            print("[sitl] armed! taking off...")
            conn.mav.command_long_send(
                conn.target_system, conn.target_component,
                mavutil.mavlink.MAV_CMD_NAV_TAKEOFF, 0,
                0, 0, 0, 0, 0, 0, altitude
            )
            time.sleep(5)
            return True
    print("[sitl] failed to arm")
    return False


def setup_sitl(conn, telemetry, speed: float = 1.0, altitude: float = 10):
    disable_sensor_noise(conn)
    set_sim_speed(conn, speed)
    setup_rangefinder(conn)
    time.sleep(0.5)
    arm_and_takeoff(conn, telemetry, altitude)


def launch_sitl_process(speed: int):
    print(f"[sitl] launching SITL at {speed}x speed...")
    cmd = (
        f"source ~/venv-ardupilot/bin/activate && "
        f"cd ~/ardupilot/ArduCopter && "
        f"sim_vehicle.py -v ArduCopter -w --console --map "
        f"--out=tcp:127.0.0.1:5760 --out=udp:127.0.0.1:14552 "
        f"--speedup={speed}"
    )
    proc = subprocess.Popen(["xterm", "-e", "bash", "-c", cmd])
    open(os.path.expanduser("~/.mavinit.scr"), "w").close()
    print("[sitl] waiting 15s for SITL to boot...")
    time.sleep(15)
    return proc


def get_sim_files() -> list[str]:
    """Return the list of sim data files to run based on command-line args."""
    sim_file = ""
    for flag in ("--sim", "-s"):
        if flag in sys.argv:
            idx = sys.argv.index(flag)
            if idx + 1 < len(sys.argv) and not sys.argv[idx + 1].startswith("-"):
                sim_file = sys.argv[idx + 1]
            break

    if sim_file.endswith(".json"):
        return [sim_file]
    elif sim_file:
        return [sim_file + ".json"]
    else:
        return [f for f in os.listdir("sim_data") if f.endswith(".json")]


def load_mission_file(file: str, base_dir: str = "sim_data", start_sim_ai: bool = True):
    """Load a mission file into the DB. Call configure_mission_dir + init_mission_log before this."""
    from ai_class import ai_storage_singleton
    from DB_abstraction import db_abstraction, Waypoint

    path = file if os.path.exists(file) else f"{base_dir}/{file}"
    with open(path, "r") as f:
        data = json.load(f)
    if start_sim_ai:
        ai_storage_singleton.start_sim_ai(data["weed_locations"])
    wps = [Waypoint(*pt, id=i) for i, pt in enumerate(data["scan_path"])]
    db_abstraction.backup_and_clear()
    for wp in wps:
        db_abstraction.add_waypoint(wp)
    return data
