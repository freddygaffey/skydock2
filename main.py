import sys
import os
import json

from ai_class import ai_storage_singleton
from telemetry import telemetry_singlton
from DB_abstraction import db_abstraction, Waypoint
from fsm import StateMachine
from sim_ai import run_sim_ai

if "-s" in sys.argv or "--sim" in sys.argv:
    print("sim mode")
    sim_file = input("sim file: ")
    if sim_file.endswith(".json"):
        files = [sim_file]
    elif sim_file != "":
        files = [sim_file + ".json"]
    else:
        files = [f for f in os.listdir("sim_data") if f.endswith(".json")]

    for file in files:
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
            pass
    
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

ai_storage_singleton.start_ai()
fsm = StateMachine()

while True:
    fsm.update()