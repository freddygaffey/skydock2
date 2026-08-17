last_goto_time = 0

# homing per-attempt timers; reset to None on every homing exit
last_det_time = None
start_homing_time = None

class Pid:
    def __init__(self,p=0.7 ,i=0.06 ,d=0) -> None:

        self.p = p
        self.i = i
        self.d = d

        self.last_time_ns = None
        self.i_sum = 0
        self.last_distance_from_target = None
        

        self.max_dt_s = 0.5
        self.max_v = 2
        self.min_v = -2


    def get_v(self, distance_from_target: float, time_ns, speedup)->float:
        i_amount, d_amount = 0, 0
        if self.last_time_ns is not None:
            dt = (time_ns - self.last_time_ns)*1e-9 * speedup
            if 0 < dt <= self.max_dt_s: 
                self.i_sum += dt*distance_from_target
                i_amount = self.i_sum * self.i
                d_amount = ((distance_from_target - self.last_distance_from_target)/dt) * self.d

        self.last_distance_from_target = distance_from_target
        self.last_time_ns = time_ns

        p_amount = distance_from_target * self.p
        amount = i_amount + d_amount + p_amount

        return min(max(amount,self.min_v),self.max_v)

    def clear_history(self):
        self.last_time_ns = None
        self.last_distance_from_target = None
        self.i_sum = 0


N_pid = Pid()
E_pid = Pid()




