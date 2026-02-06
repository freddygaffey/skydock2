from typing import Callable

class Passer:
    def __init__(self,fun: Callable, pram_and_time_dict :dict[str,float]):
        self.fun = fun
        self.pram_and_time_dict = pram_and_time_dict

target = "NAMED_VALUE_FLOAT"
def debug(msg):
    if target is not None:
        if msg is not None:
            if msg._type == target:
                print(target)
debugging_passser = Passer(debug,{})

def start_passers(debug = False):
    from telemetry import telemetry_singlton
    from move import move_singleton
    from drone_state import drone_state
    from ai_class import ai_storage
    from archive.gc_messages import gc_singlton

    telemetry_singlton.passer(move_singleton.passer)
    telemetry_singlton.passer(drone_state.passer)
    telemetry_singlton.passer(gc_singlton.passer)

    if debug:
        telemetry_singlton.passer(debugging_passser)
    # ai_storage.start_ai()


if __name__ == "__main__":
    pass
    # while 1:
    #     print(drone_state.__dict__)
    #     time.sleep(0.5)