import time
import sys

from telemetry import telemetry_singlton
from drone_state import DroneStateForHoming
from ai_class import ai_storage_singleton, Frame
from mission_logging import log_event

from states.homing import homing
from states.scan import scan
from states.spray import spraying
from states.goto import goto
from states.overide import overide
from states.rtl import rtl
from states.enum import DroneStateEnum


    
class StateMachine:
    def __init__(self):
        self.current_state = DroneStateEnum.OVERRIDE
        self._last_state_print = 0.0
        self._last_printed_state = None

    def update(self):
        frame = ai_storage_singleton.get_latest_frame()
        drone_state = telemetry_singlton.drone_state
        if not drone_state.is_telemetry_ready:
            return
        prev_state = self.current_state
        match self.current_state:
            case DroneStateEnum.OVERRIDE:
                self.current_state = self._update_override(frame,drone_state)
                # todo: remove this 
                # self.current_state = DroneStateEnum.GOTO
            case DroneStateEnum.SCAN:
                self.current_state = self._update_scan(frame,drone_state)
            case DroneStateEnum.GOTO:
                self.current_state = self._update_goto(frame,drone_state)
            case DroneStateEnum.HOMING:
                self.current_state = self._update_homing(frame,drone_state)
            case DroneStateEnum.SPRAY:
                self.current_state = self._update_spray(frame,drone_state)
            case DroneStateEnum.RTL:
                self.current_state = self._update_rtl(frame,drone_state)
                return False
            case DroneStateEnum.DONE:
                print("the mission is done")
                return False 
            case _:
                self.current_state = DroneStateEnum.OVERRIDE            
        now = time.time()
        if self.current_state != self._last_printed_state or now - self._last_state_print >= 5:
            print(self.current_state)
            self._last_printed_state = self.current_state
            self._last_state_print = now
        if prev_state != self.current_state:
            log_event(
                "fsm_transition",
                logger="fsm",
                level="INFO",
                drone_state=drone_state,
                frame=frame,
                state_from=prev_state,
                state_to=self.current_state,
            )
        else:
            log_event(
                "fsm_tick",
                logger="fsm",
                level="DEBUG",
                drone_state=drone_state,
                frame=frame,
                state=self.current_state,
            )
    

    def _update_override(self,frame:Frame,drone_state:DroneStateForHoming) -> DroneStateEnum:
        if (check := self._overide_and_rtl_checks(drone_state)):return check
        return overide(drone_state,frame)
        
    def _update_scan(self,frame:Frame,drone_state:DroneStateForHoming) -> DroneStateEnum:
        if (check := self._overide_and_rtl_checks(drone_state)):return check
        return scan(getattr(frame, 'drone_state', None) or drone_state, frame)

    def _update_goto(self,frame:Frame,drone_state:DroneStateForHoming) -> DroneStateEnum:
        if (check := self._overide_and_rtl_checks(drone_state)):return check
        return goto(drone_state,frame)

    def _update_homing(self,frame:Frame,drone_state:DroneStateForHoming) -> DroneStateEnum:
        if (check := self._overide_and_rtl_checks(drone_state)):return check

        return homing(drone_state,frame) 

    def _update_spray(self,frame:Frame,drone_state:DroneStateForHoming) -> DroneStateEnum:
        if (check := self._overide_and_rtl_checks(drone_state)):return check

        return spraying(drone_state,frame)

    def _update_rtl(self,frame:Frame,drone_state:DroneStateForHoming) -> DroneStateEnum:
        if (check := self._overide_and_rtl_checks(drone_state)):return check
        return rtl(drone_state, frame)


    def _overide_and_rtl_checks(self,drone_state:DroneStateForHoming):
        if drone_state.mode == 'RTL':
            return DroneStateEnum.RTL
        elif drone_state.mode != 'GUIDED':
            return DroneStateEnum.OVERRIDE
        else:
            return None
        


# from typing import Protocol
# import time

# from telemetry import telm_singleton, GroundStaionMessages
# from move import move_singleton 
# from ai import ai_storage_singleton, Camera
# from drone_snapshots import drone_telm_stapshot, ScanningPlanner,WeedStorage,Weed

# class DroneState(Protocol):
#     def enter(self): ...
#     def update(self): ...
#     def exit(self): ...

# class FSM:
#     def __init__(self):
#         self.state = OnGroundState()

# class OnGroundState(DroneState):
#     def enter(self) -> None:
#         print("Drone is on the ground.")
    
#     def update(self):
#         # if telm_singleton.run_pre_flight_checks() == True and "takeoff" in ground_station_commands.commands[0]:
#         if telm_singleton.run_pre_flight_checks() == True and GroundStaionMessages.ask_gc_question("Permission to move to takeoff state?"):
#             move_singleton.arm_and_take_off_to_hight(GroundStaionMessages.float_messages["takeoff_hight"])
#             return TakeOff()
#         else:
#             time.sleep(3)
#             return None

#     def exit(self) -> None:
#         print("Drone is leaving Ground state.")

# class TakeOff(DroneState):
#     def enter(self):
#         if GroundStaionMessages.ask_gc_question(f"Permission to arm and takeoff to {GroundStaionMessages.float_messages["takeoff_hight"]} m ?"):
#             move_singleton.arm_and_take_off_to_hight(GroundStaionMessages.float_messages["takeoff_hight"])
        
#     def update(self):
#         check_alt = round(drone_telm_stapshot.altitude_rel_home,1) == GroundStaionMessages.float_messages["takeoff_hight"]
#         if check_alt != True:
#             return None
#         elif Context.scaning_complete:
#             return Scaning()
#         else:
#             return SprayFSM()

#     def exit(self):
#         print("takeoff conpleate")

# class Scaning(DroneState):
#     def enter(self):
#         pass

#     def update(self):
#         """
#         while true
#             fly to next scan point 
#             while scanning add detections 
#         """
#         # update poss
#         loc = drone_telm_stapshot.longitude , drone_telm_stapshot.latitude
#         next_point = ScanningPlanner.next_point(loc)
#         if next_point is None:
#             Context.scaning_complete = True
#             return Spraying()
#         move_singleton.fly_to_point(lat=loc[1],lon=loc[0],alt_above_home=ScanningPlanner.scan_alt)

#         # add weed detections
#         frame = ai_storage_singleton.get_frames_in_time_period(less_past=time.time_ns(),more_past=Weed.time_last_mass_updated)
#         new_weeds = Weed.retun_all_new_valid_weeds(drone_state=drone_telm_stapshot,frame=frame,camera=Camera)

#         WeedStorage.add_weed(new_weeds)


#     def exit(self):
#         pass

# class RetunToHome(DroneState):
#     @classmethod
#     def need_to_RTH(cls):
#         # TODO: actally do this
#         pass

#     def enter(self):
#         move_singleton.set_mode("RTH")
#     def update(self):
#         if move_singleton.get_mode() != "RTH":
#             move_singleton.set_mode("RTH")
        

# class Spraying:
# # class SprayFSM:
# # class SprayFlyToPoint(DroneState):
# # class SprayHomeOverWeed(DroneState):
# # class SpraySpray(DroneState):

# class LightState(Protocol):
#     def switch(self, bulb) -> None:
#         ...

# class OnState(LightState):
#     def switch(self,bulb) -> None:
#         bulb.state = OffState()
#         print("The light is on.")
    
# class OffState(LightState):
#     def switch(self,bulb) -> None:
#         bulb.state = OnState()
#         print("The light is off.")

# class Bulb:
#     def __init__(self):
#         self.state = OnState()
    
#     def switch(self):
#         self.state.switch(self)

# if __name__ == "__main__":
#     bulb = Bulb()
#     bulb.switch()  # The light is off.
#     bulb.switch()  # The light is on.
