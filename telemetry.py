import threading
import time
import serial

from pymavlink import mavutil
from typing import Callable
from drone_state import DroneStateForHoming

class Telemetry(object):
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            cls.instance = super(Telemetry, cls).__new__(cls)
        return cls.instance

    def __init__(self):
        self.drone_state = DroneStateForHoming() 
        # connect to drone

        connection_palths = ["/dev/ttyACM1", "/dev/ttyACM0","/dev/ttyACM10","udp:127.0.0.1:14552",None]
        # connection_palths = ["udp:127.0.0.1:14552"]
        for i in connection_palths:
            if i is None:
                raise ConnectionError("could not connect to the fc")
            try:
                path_to_uav = i
                self.connection = mavutil.mavlink_connection(path_to_uav, baud=115200)
                self.connection.wait_heartbeat(timeout=5)
                if self.connection is not None:
                    break
            except serial.serialutil.SerialException:
                print(f"cant connect to {i}")
                pass

        self.mode_mapping = {'STABILIZE': 0,'ACRO': 1,'ALT_HOLD': 2,'AUTO': 3,'GUIDED': 4,'LOITER': 5,'RTL': 6,'CIRCLE': 7,'OF_LOITER': 10,'DRIFT': 11,'SPORT': 13,'FLIP': 14,'AUTOTUNE': 15,'POSHOLD': 16,'BRAKE': 17,'THROW': 18,'AVOID_ADSB': 19,'GUIDED_NOGPS': 20,'SMART_RTL': 21,'FLOWHOLD': 22,'FOLLOW': 23,'ZIGZAG': 24,'SYSTEMIDLE': 25,'AUTOTUNE': 26,'RALLY': 27}
        self.current_mode = None
        self.arm_state = False

        self._v_thread = None
        self._v_thread_stop_event = threading.Event()
        threading.Thread(target=self.start_passer).start()

    def start_passer(self):
        drone_state_rate = 1/35
        # drone_state_rate = 1
        self.set_a_message_interval("GLOBAL_POSITION_INT",drone_state_rate)
        self.set_a_message_interval("SERVO_OUTPUT_RAW",drone_state_rate)
        self.set_a_message_interval("ATTITUDE", drone_state_rate)
        self.set_a_message_interval("HEARTBEAT", 1)

        while True:
            try:
                msg = self.connection.recv_msg()
            except serial.SerialException: pass
            if msg is None:
                time.sleep(0.003)
                continue

            self.drone_state.set_pass_message(msg)
            self.move_msg_passer(msg)
    def run_pre_flight_checks(self):
        """retun true if good to go
        retun the arm fail message if not good to go"""
        for _ in range(5):
            self.connection.mav.command_long_send(
                self.connection.target_system,       # target_system
                self.connection.target_component,    # target_component
                mavutil.mavlink.MAV_CMD_RUN_PREARM_CHECKS,  # command 401
                0,                          # confirmation
                0, 0, 0, 0, 0, 0, 0         # params 1-7 (not used)
            )

            result = self.connection.recv_match(type='COMMAND_ACK', blocking=True,timeout=1)
            if result.command == 401:
                break

        msg = self.connection.recv_match(type='STATUSTEXT', blocking=True, timeout=1)
        if msg:
            return msg.text
        if msg is None and result.command == 401:
            return True
        else:
            return None
        # example of fialing
        # COMMAND_ACK {command : 401, result : 0, progress : 0, result_param2 : 0, target_system : 255, target_component : 0}
        # PreArm: GPS 1: Bad fix
    def set_a_message_interval(self,message_name:str,interval:float=1):
        """interval in sec"""
        # https://mavlink.io/en/mavgen_python/howto_requestmessages.html
        interval *= 1000000
        message = self.connection.mav.command_long_encode(
            self.connection.target_system,
            self.connection.target_component,
            mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,
            0,  # Confirmation
            eval(f"mavutil.mavlink.MAVLINK_MSG_ID_{message_name}"), # param1: Message streamed
            interval, # param2: Interval in microseconds
            0,0,0,0,0)

        # Send the COMMAND_LONG
        self.connection.mav.send(message)
        string_to_print = f"set {message_name} to repeat every: {str(interval/1000000)} seconds"
        print(string_to_print)

    def send_text_message(self,message:str):
        """a wrapper around a sending a text should do incoding somewhere else"""
        if len(message) > 50-4:
            raise ValueError("the send text message must be under 50 chars")
        self.connection.mav.statustext_send(
            mavutil.mavlink.MAV_SEVERITY_INFO,
            f"msg:{message}".encode("utf-8"))
    ########## MOVE ###########
    def set_mode(self, mode:str):
        if mode not in self.mode_mapping.keys():
            raise Exception("INVALID MODE (ps THIS IS FORM FREDDY)")
        self.connection.mav.command_long_send(
            self.connection.target_system,
            self.connection.target_component,
            mavutil.mavlink.MAV_CMD_DO_SET_MODE,
            0,  # Confirmation
            1,  # 1: Set mode
            self.mode_mapping[mode],  # Mode ID
            0, 0, 0, 0, 0
        )
    def get_mode(self):
        return self.current_mode
    def is_armed(self):
        # TODO: this is not garityed to work 
        return self.arm_state
    def move_msg_passer(self,msg:str):
        """retuns the currnt mode (in eglish)"""
        if msg._type == "HEARTBEAT":
            mode_id = msg.custom_mode
            current_mode = None
            for i in self.mode_mapping:
                if self.mode_mapping[i] == mode_id:
                    current_mode = i
                    break
            if msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED:
                self.arm_state = True
            else: 
                self.arm_state = False

            if current_mode ==  None: raise Exception("mode not found (freddy)")
            self.current_mode = current_mode

        # return current_mode
    def send_displacement_command_yaw_stay_same(self,mx:float,my:float,mz:float,bitmask:int=4088):
            self.connection.mav.set_position_target_local_ned_send(
                0,
                self.connection.target_system,
                self.connection.target_component,
                mavutil.mavlink.MAV_FRAME_BODY_OFFSET_NED,
                bitmask,  # ignore velocity, acceleration, yaw/yaw_rate (position only)
                mx, my, mz,  # position offsets in meters
                0, 0, 0,     # velocity ignored
                0, 0, 0,     # acceleration ignored
                0, 0         # yaw and yaw_rate ignored
                )
    def send_volocity_command_yaw_stay_same(self,mx,my,mz,bitmask=int(0b10111000111)):
        # this command must be sent every 3 seconds to continue moving
        if not bitmask:
            raise ValueError("bit mask not set for volocity command")

        self.connection.mav.set_position_target_local_ned_send(
            0,
            self.connection.target_system,
            self.connection.target_component,
            mavutil.mavlink.MAV_FRAME_BODY_OFFSET_NED,
                bitmask,  # ignore velocity, acceleration, yaw/yaw_rate (position only)
            0, 0, 0,  
            mx, my, mz,     # velocity 
            0, 0, 0,     
            0, 0         # TODO: yaw and yaw_rate 
        )
    def send_e_stop_command(self):
        old_mode = self.get_mode()
        self.set_mode("BRAKE")
        time.sleep(3)
        self.set_mode(old_mode)
        self.stop_volocity_command()
    def send_displacement_command_yaw_stay_same(self,mx,my,mz,bitmask=4088):
            self.connection.mav.set_position_target_local_ned_send(
                0,
                self.connection.target_system,
                self.connection.target_component,
                mavutil.mavlink.MAV_FRAME_BODY_OFFSET_NED,
                bitmask,  # ignore velocity, acceleration, yaw/yaw_rate (position only)
                mx, my, mz,  # position offsets in meters
                0, 0, 0,     # velocity ignored
                0, 0, 0,     # acceleration ignored
                0, 0         # yaw and yaw_rate ignored
                )
    def move_volocity_until_stop_or_max_time(self,direction,max_time,change_yaw=False):
        self.stop_volocity_command()

        def repeatedly_send_v_command(direction,max_time,change_yaw):
            dyaw = 3527
            no_dyaw = 1479 
            if change_yaw:
                bitmask = dyaw
            else:
                bitmask = no_dyaw
            start_time = time.time()
            while time.time() < start_time + max_time and not self._v_thread_stop_event.is_set():
                print("sending volocity command on thread")
                self.send_volocity_command_yaw_stay_same(direction[0],direction[1],direction[2],bitmask)
                time.sleep(0.03)
                
        if self._v_thread is None or not self._v_thread.is_alive(): # this will check if none like after init or later is not runing
            self._v_thread_stop_event.clear()
            self._v_thread = threading.Thread(target=repeatedly_send_v_command,args=(direction,max_time,change_yaw))
            self._v_thread.start()
            print("started sending move command")
    def stop_volocity_command(self):
        if self._v_thread and self._v_thread.is_alive():
            self._v_thread_stop_event.set()
            self._v_thread.join()
            # self.send_volocity_command_yaw_stay_same(0,0,0)
            self._v_thread = None 
    def arm(self): # dange UNTESTED
        # TODO: test in real world
        self.connection.mav.command_long_send(
            self.connection.target_system,
            self.connection.target_component,
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            0, 1, 0, 0, 0, 0, 0, 0
        )
        while True:
            msg = self.connection.recv_match(type='HEARTBEAT', blocking=True)
            if msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED:
                return True
            time.sleep(1)
    def arm_and_take_off_to_hight(self,hight): # danger UNTESTED
        # TODO: test in real world
            self.arm()
            self.connection.mav.command_long_send(
                self.connection.target_system,
                self.connection.target_component,
                mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
                0, 0, 0, 0, 0, 0, 0, hight
            )
    def fly_to_point(self,lat,lon,alt_above_home,bitmask=3576):
        lat = int(lat * 1e7)
        lon = int(lon * 1e7)

        self.connection.mav.set_position_target_global_int(
            0,
            self.connection.target_system,
            self.connection.target_component,
            mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
            bitmask,  # ignore velocity, acceleration, yaw/yaw_rate (position only)
            lat, lon, alt_above_home,
            0,0,0,  
            0,0,0,  
            0,0
            )

telemetry_singlton = Telemetry()

if __name__ == "__main__":
    while 1:print(telemetry_singlton.drone_state)
    pass
