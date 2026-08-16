"""Drone state snapshot built from MAVLink, plus history-based interpolation.

set_pass_message() converts raw MAVLink wire units into SI/degrees:
  GLOBAL_POSITION_INT: lat/lon degE7 -> deg, relative_alt mm -> m, v cm/s -> m/s,
    hdg cdeg -> deg (65535 = unknown -> None).
  ATTITUDE: roll/pitch/yaw radians (kept in rotation + rotation_history).
  HEARTBEAT: flight mode (custom_mode) and arm_state (base_mode armed flag).
  RC_CHANNELS: chan16 PWM 3-position switch -> autonomy_enabled / force_homing
    (>1700 force-homing, <1300 autonomy, mid disables); always-on in sim.
  DISTANCE_SENSOR: current_distance cm -> rangefinder_m.

get_position_at_time / get_rotation_at_time dead-reckon and Hermite-interpolate
to a detection timestamp so projections line up with when the frame was captured.
"""

from dataclasses import dataclass, field
from sys import exc_info
from pymavlink import mavutil
from collections import deque
import math
from math import cos, radians
import time
import constants

# EXPERIMENTAL camera pixel->body axis mapping: ray_body = CAM_TO_BODY @ [x_cam, y_cam, 1].
# Measured from the May 2026 flight logs by three independent methods (surveyed-truth fit,
# forward optical flow, yaw-rotation handedness) — see tools/camera_orientation_from_flow.py
# and docs/Bug Notes.md. Result: image-right = body-BACKWARD (x mirrored), image-down =
# body-RIGHT. Same sensor and mount on every flight since, so it should hold for the
# current 640x640 config — re-verify on the first flight with the flow tool.
# The old (wrong) assumption was identity.
CAM_TO_BODY = (
    (-1.0, 0.0, 0.0),
    ( 0.0, 1.0, 0.0),
    ( 0.0, 0.0, 1.0),
)
@dataclass
class GPSFix:
    time_ns: float
    lat: float
    lon: float
    vx: float  # m/s North
    vy: float  # m/s East


@dataclass
class Rotation:
    time_ns: float
    x: float
    y: float
    z: float
    dx: float = 0
    dy: float = 0
    dz: float = 0



@dataclass
class DroneStateForHoming:
    # time_to_boot_real_time_ofset:float = 0
    time_updated_GLOBAL_POSITION_INT: float = 0
    time_updated_angle: float = 0
    wall_sim_time: deque = field(default_factory=lambda: deque(maxlen=100))
    sim_speed: float = constants.TARGET_SIM_SPEED
    # Global position in degrees/meters
    latitude: float = 0
    longitude: float = 0
    altitude_rel_home: float = 0 # rel form ground

    # Velocity in m/s in local NED frame
    velocity_x: float = 0.0
    velocity_y: float = 0.0
    velocity_z: float = 0.0

    autonomy_enabled: bool = True
    force_homing: bool = False
    arm_state: bool = False  # set from HEARTBEAT.base_mode in set_pass_message
    mode: str = 'STABILIZE'

    heading: float = 0
    
    rotation:Rotation = field(default_factory=lambda: Rotation(0,0,0,0))
    rotation_history: deque = field(default_factory=lambda: deque(maxlen=100))
    gps_history: deque = field(default_factory=lambda: deque(maxlen=100))

    # MAVLink DISTANCE_SENSOR.current_distance is centimeters (common.xml). Convert to metres here.
    rangefinder_m: float = 0.0  # slant range from co-axial rangefinder, metres; 0 = no data

    height: int = 1280
    width: int = 1280

    # RPi HQ Camera (IMX477, 1.55 µm pixel pitch, 4056x3040 active) + 6mm CS lens.
    # Active Picamera2 sensor mode is 2028x1080 (binned), crop_limits (0, 440, 4056, 2160) -
    # full sensor width, top/bottom 440 px cropped by the sensor mode. The lores stream
    # stretches that area into 640x640 with preserve_ar=False, so buffer pixels are
    # non-square and per-axis FOV must reflect each axis's sensor coverage independently.
    SENSOR_PIXEL_PITCH_MM = 0.00155
    LENS_FOCAL_LENGTH_MM = 6.0
    SENSOR_W_PX = 4056
    SENSOR_H_PX = 2160

    @property
    def fov_x_deg(self) -> float:
        half = self.SENSOR_W_PX * self.SENSOR_PIXEL_PITCH_MM / 2.0
        return 2.0 * math.degrees(math.atan(half / self.LENS_FOCAL_LENGTH_MM))

    @property
    def fov_y_deg(self) -> float:
        half = self.SENSOR_H_PX * self.SENSOR_PIXEL_PITCH_MM / 2.0
        return 2.0 * math.degrees(math.atan(half / self.LENS_FOCAL_LENGTH_MM))

    @property
    def is_telemetry_ready(self) -> bool:
        # First ATTITUDE message populates rotation_history; before that, projections
        # would assume zero attitude and produce wildly wrong NED offsets.
        return len(self.rotation_history) > 0

    def set_pass_message(self,msg):
        if msg is None:
            return 0

        if msg._type == "HEARTBEAT":
            if msg.type == mavutil.mavlink.MAV_TYPE_GCS:
                return
            mode_mapping = {'STABILIZE': 0,'ACRO': 1,'ALT_HOLD': 2,'AUTO': 3,'GUIDED': 4,'LOITER': 5,'RTL': 6,'CIRCLE': 7,'LAND': 8,'OF_LOITER': 10,'DRIFT': 11,'SPORT': 13,'FLIP': 14,'AUTOTUNE': 15,'POSHOLD': 16,'BRAKE': 17,'THROW': 18,'AVOID_ADSB': 19,'GUIDED_NOGPS': 20,'SMART_RTL': 21,'FLOWHOLD': 22,'FOLLOW': 23,'ZIGZAG': 24,'SYSTEMIDLE': 25,'AUTOROTATE': 26,'RALLY': 27}
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

            if current_mode is None:
                print(f"WARNING: unknown mode id {mode_id}, keeping current mode '{self.mode}'")
                return
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

            self.gps_history.append(GPSFix(
                time_ns=time.time_ns(),
                lat=self.latitude,
                lon=self.longitude,
                vx=self.velocity_x,
                vy=self.velocity_y,
            ))

        if msg._type == "RC_CHANNELS":
            import sys
            if "-s" in sys.argv or "--sim" in sys.argv:
                self.autonomy_enabled = True
                self.force_homing = False
            else:
                # 3-pos switch on chan16: up (~2099) = force_homing, mid (~1500) = disable, down (~900) = autonomy
                pwm = msg.chan16_raw
                if pwm > 1700:
                    self.force_homing = True
                    self.autonomy_enabled = True
                elif pwm < 1300:
                    self.autonomy_enabled = True
                    self.force_homing = False
                else:
                    self.autonomy_enabled = False
                    self.force_homing = False

            # # TODO: remove
            # self.rotation_x = 0.0
            # self.rotation_y = 0.0
            # self.rotation_z = 0.0

        if msg._type == "DISTANCE_SENSOR":
            # current_distance is uint16 cm (see MAVLink DISTANCE_SENSOR).
            self.rangefinder_m = float(msg.current_distance) * 0.01

        if msg._type == "ATTITUDE":
            rot = Rotation(
                time_ns=time.time_ns(),
                x=msg.roll,
                y=msg.pitch,
                z=msg.yaw,
                dx=msg.rollspeed,
                dy=msg.pitchspeed,
                dz=msg.yawspeed,
            )
            self.rotation_history.append(rot)
            self.rotation = rot

        if msg._type == "SYSTEM_TIME":
            self.wall_sim_time.append([time.time_ns(),msg.time_boot_ms])
            self.update_sim_speedup()

    def to_db_format(self):
        return (self.time_updated_GLOBAL_POSITION_INT,
                self.longitude,
                self.latitude,
                self.altitude_rel_home,
                self.heading,
                self.autonomy_enabled,
                self.rotation.x,
                self.rotation.y,
                self.rotation.z,
                self.mode)

    def get_position_at_time(self, time_ns: float) -> 'GPSFix':
        """Dead-reckon lat/lon to time_ns using the GPS history (wall-clock timestamps)."""
        if not self.gps_history:
            return GPSFix(time_ns, self.latitude, self.longitude, self.velocity_x, self.velocity_y)
        fix = self.gps_history[-1]
        dt_s = (time_ns - fix.time_ns) * 1e-9
        dlat = fix.vx * dt_s / 111320
        dlon = fix.vy * dt_s / (111320 * cos(radians(fix.lat)))
        return GPSFix(time_ns, fix.lat + dlat, fix.lon + dlon, fix.vx, fix.vy)

    def get_rotation_at_time(self, time_ns: float) -> 'Rotation':
        before = None
        after = None
        for rot in self.rotation_history:
            if rot.time_ns <= time_ns:
                before = rot
            else:
                after = rot
                break

        if before is None:
            return self.rotation

        if after is None:
            # Extrapolate forward from the last known entry using its angular rates.
            # dx/dy/dz are rad/s; dt_s converts ns gap to seconds.
            dt_s = (time_ns - before.time_ns) * 1e-9
            return Rotation(
                time_ns=time_ns,
                x=before.x + before.dx * dt_s,
                y=before.y + before.dy * dt_s,
                z=before.z + before.dz * dt_s,
                dx=before.dx,
                dy=before.dy,
                dz=before.dz,
            )

        dt_ns = after.time_ns - before.time_ns
        dt_s  = dt_ns * 1e-9
        t = (time_ns - before.time_ns) / dt_ns  # normalised 0..1

        # Cubic Hermite interpolation — matches value AND derivative at both endpoints.
        # Tangents are m [rad/s] * dt_s [s] = radians, matching the angle units.
        h00 =  2*t**3 - 3*t**2 + 1
        h10 =    t**3 - 2*t**2 + t
        h01 = -2*t**3 + 3*t**2
        h11 =    t**3 -   t**2

        def hermite(p0, m0, p1, m1):
            return h00*p0 + h10*(m0*dt_s) + h01*p1 + h11*(m1*dt_s)

        return Rotation(
            time_ns=time_ns,
            x  = hermite(before.x,  before.dx, after.x,  after.dx),
            y  = hermite(before.y,  before.dy, after.y,  after.dy),
            z  = hermite(before.z,  before.dz, after.z,  after.dz),
            dx = before.dx + t * (after.dx - before.dx),
            dy = before.dy + t * (after.dy - before.dy),
            dz = before.dz + t * (after.dz - before.dz),
        )

    def update_sim_speedup(self):
        try:
            d_wall_ms = (self.wall_sim_time[-1][0] - self.wall_sim_time[0][0]) // 1e6
            d_fc_ms = self.wall_sim_time[-1][1] - self.wall_sim_time[0][1]
            measured = d_fc_ms / d_wall_ms
            self.sim_speed += (measured - self.sim_speed) * 0.5
        except ZeroDivisionError:
            pass
