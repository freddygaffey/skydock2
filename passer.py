from typing import Callable

class Passer:
    def __init__(self,fun: Callable, pram_and_time_dict :dict[str,float]):
        self.fun = fun
        self.pram_and_time_dict = pram_and_time_dict
