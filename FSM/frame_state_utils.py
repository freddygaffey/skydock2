from ai_class import Detection
from drone_state import DroneStateForHoming
from math import radians, tan


def rotate_det(det,dgr):
    # TODO: actualy make work
    return det

def calulate_s_for_drone_state_and_frame(drone_state: DroneState, detection: Detection) -> float:
    detection = rotate_det(detection)
    MIN_HIGHT = 1 # m
    MAX_SPEED = 3 # m/s
    
    # all camera parameters are relative to ned of the drone not the camera xy 
    CAMERA_FOV_X = 27.4 # TODO: make this actually right
    CAMERA_FOV_y = 21.0 # TODO: make this actually right
    NUM_OF_PIX_X = 1280 # TODO: make this actually right
    NUM_OF_PIX_Y = 720  # TODO: make this actually right
 
    def calculate_displacement(angle_of_drone, alt, fov, nomolised_pos) -> float:
        target_angle = (nomolised_pos - 0.5) * radians(fov) 
        ned_angle = angle_of_drone + target_angle
        return alt * tan(ned_angle)
    
    xs = calculate_displacement(drone_state.rotation[0],
                                drone_state.altitude_rel_home,
                                CAMERA_FOV_X,
                                detection.get_center()[0])
                                
    ys = calculate_displacement(drone_state.rotation[1],
                                drone_state.altitude_rel_home,
                                CAMERA_FOV_y,
                                detection.get_center()[1])
    
    return xs, ys

    