"""Mission finite-state machine.

StateMachine.update() is called ~30 Hz from main.py. Each tick it reads the
latest AI Frame and the current DroneStateForHoming, dispatches to the handler
for the current state, logs the result, and returns:

  * None  -> keep looping (normal tick)
  * False -> stop the mission loop (RTL or DONE reached)

Every non-terminal handler first runs _override_and_rtl_checks(), so a pilot
mode change (out of GUIDED, or into RTL) always pre-empts autonomous behaviour.
States: OVERRIDE, SCAN, GOTO, HOMING, SPRAY, RTL, DONE (see states/enum.py).
"""

import time

from telemetry import telemetry_singleton
from drone_state import DroneStateForHoming
from ai_class import ai_storage_singleton, Frame
from mission_logging import log_event

from states.homing import homing
from states.scan import scan
from states.spray import spraying
from states.goto import goto
from states.override import override
from states.rtl import rtl
from states.enum import DroneStateEnum



class StateMachine:
    def __init__(self):
        self.current_state = DroneStateEnum.OVERRIDE
        self._last_state_print = 0.0
        self._last_printed_state = None

    def update(self):
        """Run one FSM tick. Returns False to stop the loop, None otherwise.

        No-ops (returns None) until telemetry is ready (first ATTITUDE received),
        so projections never run against a zero-attitude state.
        """
        frame = ai_storage_singleton.get_latest_frame()
        drone_state = telemetry_singleton.drone_state
        if not drone_state.is_telemetry_ready:
            return
        prev_state = self.current_state
        match self.current_state:
            case DroneStateEnum.OVERRIDE:
                self.current_state = self._update_override(frame,drone_state)
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
        if (check := self._override_and_rtl_checks(drone_state)):return check
        return override(drone_state,frame)
        
    def _update_scan(self,frame:Frame,drone_state:DroneStateForHoming) -> DroneStateEnum:
        if (check := self._override_and_rtl_checks(drone_state)):return check
        return scan(getattr(frame, 'drone_state', None) or drone_state, frame)

    def _update_goto(self,frame:Frame,drone_state:DroneStateForHoming) -> DroneStateEnum:
        if (check := self._override_and_rtl_checks(drone_state)):return check
        return goto(drone_state,frame)

    def _update_homing(self,frame:Frame,drone_state:DroneStateForHoming) -> DroneStateEnum:
        if (check := self._override_and_rtl_checks(drone_state)):return check

        return homing(drone_state,frame) 

    def _update_spray(self,frame:Frame,drone_state:DroneStateForHoming) -> DroneStateEnum:
        if (check := self._override_and_rtl_checks(drone_state)):return check

        return spraying(drone_state,frame)

    def _update_rtl(self,frame:Frame,drone_state:DroneStateForHoming) -> DroneStateEnum:
        if (check := self._override_and_rtl_checks(drone_state)):return check
        return rtl(drone_state, frame)


    def _override_and_rtl_checks(self,drone_state:DroneStateForHoming):
        if drone_state.mode == 'RTL':
            return DroneStateEnum.RTL
        elif drone_state.mode != 'GUIDED':
            return DroneStateEnum.OVERRIDE
        else:
            return None
