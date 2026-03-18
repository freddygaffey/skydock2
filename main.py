import sys
import os
import json

from ai_class import ai_storage_singleton
from telemetry import telemetry_singlton
from DB_abstraction import db_abstraction, Waypoint
from fsm import StateMachine
from sim_ai import run_sim_ai
from mission_logging import init_mission_log
from states.constants import MIN_SPRAY_ERROR

if "-s" in sys.argv or "--sim" in sys.argv:
    print("sim mode")
    # Accept an optional sim filename on the command line:
    #   python main.py --sim cmac
    #   python main.py --sim cmac.json
    # If not provided (or stdin is non-interactive), run all sim_data/*.json.
    sim_file = ""
    try:
        sim_idx = sys.argv.index("--sim")
    except ValueError:
        try:
            sim_idx = sys.argv.index("-s")
        except ValueError:
            sim_idx = -1

    if sim_idx != -1 and sim_idx + 1 < len(sys.argv) and not sys.argv[sim_idx + 1].startswith("-"):
        sim_file = sys.argv[sim_idx + 1]
    elif sys.stdin.isatty():
        sim_file = input("sim file (blank = all): ").strip()

    if sim_file.endswith(".json"):
        files = [sim_file]
    elif sim_file != "":
        files = [sim_file + ".json"]
    else:
        files = [f for f in os.listdir("sim_data") if f.endswith(".json")]

    for file in files:
        # Create mission.jsonl header as soon as we know which sim file is being used.
        init_mission_log(
            is_sim=True,
            # Store just the filename so the log viewer can pass it to /sim_compare.
            # (Older logs may include "sim_data/..." and are handled in the UI.)
            sim_truth_file=file,
            weed_match_m=0.5,
            min_spray_error_m=float(MIN_SPRAY_ERROR),
        )
        with open(f"sim_data/{file}", "r") as f:
            data = json.load(f)
            weeds = data["weed_locations"]
            ai_storage_singleton.start_ai(weeds)
            scan_path = data["scan_path"]
            wps_new = []
            id = 0
            for i in scan_path:
                wp = Waypoint(*i,id=id)
                wps_new.append(wp)
                id += 1
            
            db_abstraction.backup_and_clear()
            for i in wps_new:
                db_abstraction.add_waypoint(i)
        fsm = StateMachine()
        while fsm.update() != False:
            # Avoid a 100% CPU tight loop in sim.
            # The FSM only changes meaningfully as telemetry + sim_ai update.
            import time
            time.sleep(1/30)
    
print("you are about to fly do your prflight checks")
print("press r to resume")
print("press n for a new mission from the currently saved auto mission")
print("press c to cancel and ctrl + c should also stop it at any time mabey")
print("w just uplod a weed location this is where home is")

inp = input("press r/n/c/w ")

if inp == "n":
    wps_new = []
    old_wps = db_abstraction.get_all_waypoints()
    id = 0
    for i in telemetry_singlton.get_auto_mission_wp():
        wp = Waypoint(*i,id=id)
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
    lon,lat = telemetry_singlton.drone_state.longitude, telemetry_singlton.drone_state.latitude
    wp = Waypoint(lon=lon,lat=lat)
    db_abstraction.add_waypoint(wp)

else:
    exit()

if input("type y when taken off (y) ") != "y":
    exit()

init_mission_log(
    is_sim=False,
    weed_match_m=0.5,
    min_spray_error_m=float(MIN_SPRAY_ERROR),
)
ai_storage_singleton.start_ai()
fsm = StateMachine()

while True:
    fsm.update()