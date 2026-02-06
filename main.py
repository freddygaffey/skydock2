from ai_class import ai_storage_singleton
from telemetry import telemetry_singlton
from DB_abstraction import db_abstraction, Waypoint
from fsm import StateMachine

# print("you are about to fly do your prflight checks")
# print("press r to resume")
# print("press n for a new mission from the currently saved auto mission")
# print("press c to cancel and ctrl + c should also stop it at any time mabey")

# inp = input("press r/n/c")

# if inp == "n":
#     wps_new = []
#     old_wps = db_abstraction.get_all_waypoints()
#     id = 0
#     for i in telemetry_singlton.get_auto_mission_wp():
#         wp = Waypoint(*i,id=id)
#         wps_new.append(wp)
#         id += 1

#     if len(wps_new) != len(old_wps):
#         db_abstraction.backup_and_clear()
#         for i in wps_new:
#             db_abstraction.add_waypoint(i)
# elif inp == "r":
#     if input("permishion to take off (y)") == "y":
#         telemetry_singlton.arm_and_take_off_to_hight(10)
# else:
#     exit()
ai_storage_singleton.start_ai()
fsm = StateMachine()
while True:
    fsm.update()