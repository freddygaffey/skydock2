import threading
import time
import serial
# import numpy as np

from pymavlink import mavutil
from typing import Callable

from passer import Passer


class Telemetry:
    def __init__(self):

        self.passer_has_started:bool = False
        self.passer_fuctions:list[Callable]= []

        count_of_time_passed = 0
        # connect to drone

        connection_palths = ["/dev/ttyACM1", "/dev/ttyACM0","/dev/ttyACM10"]
        for i in connection_palths:
            try:
                path_to_uav = i
                self.connection = mavutil.mavlink_connection(path_to_uav, baud=115200)
                self.connection.wait_heartbeat()
                # Lazy import to avoid circular dependency
                from move import move_singleton
                move_singleton.connection = self.connection
            except serial.serialutil.SerialException:
                count_of_time_passed += 1

        if count_of_time_passed == len(connection_palths):
            raise ConnectionError("could not connect to the fc")
        
        threading.Thread(target=self.start_passer,daemon=True).start()
    def passer(self,passer:Passer):
        """adds a functon that will be passed be the passer and the interval"""    
        for i in passer.pram_and_time_dict:
            self.set_a_message_interval(i,passer.pram_and_time_dict[i]) # the name and the time

        self.passer_fuctions.append(passer.fun)
    def start_passer(self):
        """this will itrate over the array of functons that are passed by the passer function"""
        while True:
            try:
                msg = self.connection.recv_msg()
            except serial.SerialException: pass

            if msg is None:
                time.sleep(0.003)
                continue

            for i in self.passer_fuctions:
                i(msg)

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

telemetry_singlton = Telemetry()