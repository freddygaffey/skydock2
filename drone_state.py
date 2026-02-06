from dataclasses import dataclass
from pymavlink import mavutil

@dataclass
class DroneStateForHoming:
    time_updated_GLOBAL_POSITION_INT: float = 0
    # Global position in degrees/meters
    latitude: float = 0
    longitude: float = 0
    altitude_rel_home: float = 0 # rel form ground

    # Velocity in m/s in local NED frame
    velocity_x: float = 0.0
    velocity_y: float = 0.0
    velocity_z: float = 0.0

    enable_homing_and_autonomy: bool = False
    mode: str = 'STABILIZE'

    heading: float = 0
    rotaion_x: float = 0 # in rad 
    rotaion_y: float = 0 # in rad 
    rotaion_z: float = 0 # in rad 

    def set_pass_message(self,msg):
        if msg is None:
            return 0

        if msg._type == "HEARTBEAT":
            mode_mapping = {'STABILIZE': 0,'ACRO': 1,'ALT_HOLD': 2,'AUTO': 3,'GUIDED': 4,'LOITER': 5,'RTL': 6,'CIRCLE': 7,'OF_LOITER': 10,'DRIFT': 11,'SPORT': 13,'FLIP': 14,'AUTOTUNE': 15,'POSHOLD': 16,'BRAKE': 17,'THROW': 18,'AVOID_ADSB': 19,'GUIDED_NOGPS': 20,'SMART_RTL': 21,'FLOWHOLD': 22,'FOLLOW': 23,'ZIGZAG': 24,'SYSTEMIDLE': 25,'AUTOTUNE': 26,'RALLY': 27}
            mode_id = msg.custom_mode
            current_mode = None
            for i in mode_mapping:
                if mode_mapping[i] == mode_id:
                    current_mode = i
                    break
            if msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED:
                self.arm_state = True
            else: 
                self.arm_state = False

            if current_mode ==  None: raise Exception("mode not found (freddy)")
            self.mode = current_mode

        if msg._type == "GLOBAL_POSITION_INT":
        # if True:
            self.time_updated_GLOBAL_POSITION_INT = msg.time_boot_ms / 1000.0  # ms → s

            # Position
            self.latitude = msg.lat / 1e7
            self.longitude = msg.lon / 1e7
            self.altitude_rel_home = msg.relative_alt / 1000.0  # mm → m

            # Velocity
            self.velocity_x = msg.vx / 100.0  # cm/s → m/s
            self.velocity_y = msg.vy / 100.0
            self.velocity_z = msg.vz / 100.0

            # Heading 65535 = unknown)
            self.heading = msg.hdg / 100.0 if msg.hdg != 65535 else None

        if msg._type == "SERVO_OUTPUT_RAW":
            if msg.servo8_raw <= 1000:
                self.enable_homing_and_autonomy = False
            if msg.servo8_raw > 1000:
                self.enable_homing_and_autonomy = True

        if msg._type == "ATTITUDE":
            self.rotaion_x = msg.roll 
            self.rotaion_y = msg.pitch
            self.rotaion_z = msg.yaw

    def to_db_format(self):
        return (self.time_updated_GLOBAL_POSITION_INT,
                self.longitude,
                self.latitude,
                self.altitude_rel_home,
                self.heading,
                self.enable_homing_and_autonomy,
                self.rotaion_x,
                self.rotaion_y,
                self.rotaion_z,
                self.mode)