last_goto_time = 0

# homing per-attempt timers; reset to None on every homing exit
last_det_time = None
start_homing_time = None

class Pid:
    def __init__(self
                 ,p=0.7
                 ,i=0.002
                 ,d=0) -> None:

        self.p = p
        self.i = i
        self.d = d

        self.error_history = [0]
        self.max_v = 2
        self.min_v = -2


    def get_v(self,distance_from_target: float)->float:
        self.error_history.append(distance_from_target)

        i_amount = sum(self.error_history)*self.i 

        p_amount = distance_from_target * self.p

        d_amount = (self.error_history[-1] - self.error_history[-2]) * self.d
        amount = i_amount + d_amount + p_amount

        return min(max(amount,self.min_v),self.max_v)

    def clear_history(self):
        self.error_history = [0]

N_pid = Pid()
E_pid = Pid()




