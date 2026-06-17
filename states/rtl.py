from drone_state import DroneStateForHoming
from ai_class import Frame
from states.enum import DroneStateEnum


def rtl(drone_state: DroneStateForHoming, frame: Frame) -> DroneStateEnum:
    """Terminal mission state: signal the FSM loop to stop.

    Returning DONE lets StateMachine.update() end the loop cleanly (and main.py's
    finally-block run kill_sim/cleanup). Note the FSM's RTL case also returns
    False directly, so this runs only on the explicit RTL->rtl() path. The actual
    return-to-launch flight is handled by ArduPilot once the FC is in RTL mode.
    """
    print("rtl state reached, ending mission loop")
    return DroneStateEnum.DONE
