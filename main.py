import time

from telemetry import telemetry_singlton
from move import move_singleton
from drone_state import drone_state

telemetry_singlton.passer(move_singleton.passer)
telemetry_singlton.passer(drone_state.passer)

while 1:
    print(drone_state.__dict__)
    time.sleep(0.5)
    

