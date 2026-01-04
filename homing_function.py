import time 

from ai_class import Camera, Detection, ai_storage_singleton
from move import move_singleton 
from drone_state import drone_state, DroneStateForHoming

def homeing(camera:Camera,
            ai_frame:list[Detection],
            poss:DroneStateForHoming):

    if not ai_frame:
        return None

    # filter for the most confidnt det in the targeted objects 
    targeted_obj = ["sports_ball","frisby"] 

    ai_frame_temp = []    
    for i in ai_frame:
        if i.label in targeted_obj:
            ai_frame_temp.append(i)

    ai_frame = ai_frame_temp

    max_conf = 0
    max_det = None
    for i in ai_frame:
        if i.confidence > max_conf:
            max_conf = i.confidence
            max_det = i 

    frame = max_det
    
    dist_x_ned = Camera.y_dist_per_pix_per_meter * poss.altitude_rel_home * frame.get_the_vector_center()[1]  # Camera Y → Drone X
    dist_y_ned = -Camera.x_dist_per_pix_per_meter * poss.altitude_rel_home * frame.get_the_vector_center()[0]  # -Camera X → Drone Y
    
    move_singleton.send_displacement_command_yaw_stay_same(dist_x_ned,dist_y_ned,poss.altitude_rel_home)

    return dist_x_ned, dist_y_ned


if __name__ == "__main__":
    from telemetry import telemetry_singlton
    from move import move_singleton
    from drone_state import drone_state
    from ai_callback import start_mock

    telemetry_singlton.passer(move_singleton.passer)
    telemetry_singlton.passer(drone_state.passer)
    start_mock()

    while True:
        print(homeing())
        time.sleep(0.5)
        



