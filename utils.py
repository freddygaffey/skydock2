from ai_class import Detection
from drone_state import DroneStateForHoming
from math import radians, tan
import math
import numpy as np

def detection_to_ned(drone_state: DroneStateForHoming, detection: Detection):
    if not drone_state.is_telemetry_ready:
        return float('inf'), float('inf')
    NUM_OF_PIX_X = drone_state.width
    NUM_OF_PIX_Y = drone_state.hight

    fx = NUM_OF_PIX_X / (2 * np.tan(np.radians(drone_state.fov_x_deg/2)))
    fy = NUM_OF_PIX_Y / (2 * np.tan(np.radians(drone_state.fov_y_deg/2)))
    cx = NUM_OF_PIX_X/2
    cy = NUM_OF_PIX_Y/2

    x_cam = (detection.get_center()[0] - cx)/fx
    y_cam = (detection.get_center()[1] - cy)/fy
    
    cam_ray = np.array([x_cam,y_cam,1])
    cam_ray = cam_ray / np.linalg.norm(cam_ray)

    # Camera is nadir-mounted, frame aligned with body: x=forward(N), y=right(E), z=down
    R_cam_to_body = np.eye(3)

    ray_body = R_cam_to_body @ cam_ray
    drone_state.rotaion = drone_state.get_rotation_at_time(detection.time_ns)
    roll,pitch,yaw = drone_state.rotaion.x,drone_state.rotaion.y,drone_state.rotaion.z

    Rx = np.array([
        [1,  0, 0],
        [0,  np.cos(roll),  -np.sin(roll)],
        [0,  np.sin(roll),   np.cos(roll)]
    ])

    Ry = np.array([
        [np.cos(pitch),  0,  np.sin(pitch)],
        [0, 1, 0],
        [-np.sin(pitch), 0,  np.cos(pitch)]
    ])

    Rz = np.array([
        [np.cos(yaw), -np.sin(yaw), 0],
        [np.sin(yaw),  np.cos(yaw), 0],
        [0, 0, 1]
    ])

    ray_to_ned = Rz @ Ry @ Rx
    ray_NED = ray_to_ned @ ray_body

    # Reject geometry where camera ray points up or sideways: ray_NED[2] near zero or negative
    # means the ray does not intersect the ground plane ahead of the drone. max() would otherwise
    # silently flip a negative ray to a phantom forward projection.
    if ray_NED[2] < 0.3:
        return float('inf'), float('inf')

    if 0.3 < drone_state.rangefinder_m < 12:
        rng_NED = ray_to_ned @ np.array([0.0, 0.0, 1.0])
        h = drone_state.rangefinder_m * rng_NED[2]
        multiply_factor = h / ray_NED[2]
    else:
        multiply_factor = drone_state.altitude_rel_home / ray_NED[2]

    N = multiply_factor * ray_NED[0]
    E = multiply_factor * ray_NED[1]
    return N, E

def detection_to_dist(drone_state: DroneStateForHoming, detection: Detection):
    NE = detection_to_ned(drone_state,detection)
    return (NE[0]**2 + NE[1]**2)**0.5


def detection_to_latlon(drone_state: DroneStateForHoming, detection: Detection) -> tuple[float, float]:
    N, E = detection_to_ned(drone_state,detection)
    gps = drone_state.get_position_at_time(detection.time_ns)
    dlat = N / 111320
    dlon = E / (111320*np.cos(radians(gps.lat)))
    return gps.lat + dlat, gps.lon + dlon
    
def latlon_to_pixel(drone_state, weed_lat: float, weed_lon: float, time_ns: int = 0) -> tuple[float, float] | None:
    """Back-project a known GPS position to pixel (px, py) in the current frame.

    Inverse of detection_to_ned(). Returns (px, py) if within the image,
    otherwise None (point not visible in this frame).
    """
    NUM_OF_PIX_X = drone_state.width
    NUM_OF_PIX_Y = drone_state.hight

    fx = NUM_OF_PIX_X / (2 * np.tan(np.radians(drone_state.fov_x_deg / 2)))
    fy = NUM_OF_PIX_Y / (2 * np.tan(np.radians(drone_state.fov_y_deg / 2)))
    cx = NUM_OF_PIX_X / 2
    cy = NUM_OF_PIX_Y / 2

    rot = drone_state.get_rotation_at_time(time_ns)
    roll, pitch, yaw = rot.x, rot.y, rot.z

    Rx = np.array([
        [1, 0, 0],
        [0,  np.cos(roll), -np.sin(roll)],
        [0,  np.sin(roll),  np.cos(roll)],
    ])
    Ry = np.array([
        [ np.cos(pitch), 0, np.sin(pitch)],
        [0, 1, 0],
        [-np.sin(pitch), 0, np.cos(pitch)],
    ])
    Rz = np.array([
        [np.cos(yaw), -np.sin(yaw), 0],
        [np.sin(yaw),  np.cos(yaw), 0],
        [0, 0, 1],
    ])
    ray_to_ned = Rz @ Ry @ Rx

    # NED offset from drone to weed (metres)
    N = (weed_lat - drone_state.latitude) * 111320
    E = (weed_lon - drone_state.longitude) * (111320 * np.cos(radians(drone_state.latitude)))

    # Vertical component (positive-down in NED = altitude)
    if 0.3 < drone_state.rangefinder_m < 12:
        rng_ned = ray_to_ned @ np.array([0.0, 0.0, 1.0])
        h = drone_state.rangefinder_m * rng_ned[2]
    else:
        h = drone_state.altitude_rel_home

    if h <= 0:
        return None

    ned_vec = np.array([N, E, h])
    ray_body = ray_to_ned.T @ ned_vec  # inverse rotation

    if ray_body[2] <= 0:
        return None  # behind the camera

    x_cam = ray_body[0] / ray_body[2]
    y_cam = ray_body[1] / ray_body[2]
    px = cx + fx * x_cam
    py = cy + fy * y_cam

    if 0 <= px <= NUM_OF_PIX_X and 0 <= py <= NUM_OF_PIX_Y:
        return float(px), float(py)
    return None


def haversine_distance(lat1, lon1, lat2, lon2) -> float:
    """Calculate the great-circle distance between two GPS points in meters."""
    R = 6371000  # Earth radius in meters
    # lat1, lon1 = poss_1
    # lat2, lon2 = poss_2

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2) ** 2 + \
        math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c