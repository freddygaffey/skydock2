from ai_class import Detection
from drone_state import DroneStateForHoming
from math import radians, tan
import math
import numpy as np

def detection_to_ned(drone_state: DroneStateForHoming, detection: Detection):
    CAMERA_FOV_X = 27.4
    CAMERA_FOV_Y = 21.0
    NUM_OF_PIX_X = 640
    NUM_OF_PIX_Y = 640

    fx = NUM_OF_PIX_X / (2 * np.tan(np.radians(CAMERA_FOV_X/2)))
    fy = NUM_OF_PIX_Y / (2 * np.tan(np.radians(CAMERA_FOV_Y/2)))
    cx = NUM_OF_PIX_X/2
    cy = NUM_OF_PIX_Y/2

    x_cam = (detection.get_center()[0] - cx)/fx
    y_cam = (detection.get_center()[1] - cy)/fy
    
    cam_ray = np.array([x_cam,y_cam,1])
    cam_ray = cam_ray / np.linalg.norm(cam_ray)

    camera_rotation = 0 # rotaiain in dgr
    rho = np.deg2rad(camera_rotation)

    R_cam_to_body = np.array([
        [np.cos(rho), -np.sin(rho), 0],
        [np.sin(rho),  np.cos(rho), 0],
        [0, 0, 1]]) @ np.array([
            [0,  1,  0],
            [1,  0,  0],
            [0,  0, -1] 
            ])

    ray_body = R_cam_to_body @ cam_ray
    roll,pitch,yaw = drone_state.rotaion_x,drone_state.rotaion_y,drone_state.rotaion_z

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

    multiply_factor = drone_state.altitude_rel_home / ray_NED[2]
    N = multiply_factor * ray_NED[0]
    E = multiply_factor * ray_NED[1]
    return N, E
def detection_to_dist(drone_state: DroneStateForHoming, detection: Detection):
    NE = detection_to_ned(drone_state,detection)
    return (NE[0]**2 + NE[1]**2)**0.5

def detection_to_latlon(drone_state: DroneStateForHoming, detection: Detection):
    N, E = detection_to_ned(drone_state,detection)
    dlat = N / 111320
    dlon = E / (111320*np.cos(radians(drone_state.latitude)))

    lat = dlat + drone_state.latitude
    lon = dlon + drone_state.longitude
    return lat, lon
    
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