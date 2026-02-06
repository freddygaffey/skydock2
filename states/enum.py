from enum import Enum, auto

class DroneStateEnum(Enum):
    OVERRIDE = auto()
    SCAN = auto()
    GOTO = auto()
    HOMING = auto()
    SPRAY = auto()
    RTL = auto()