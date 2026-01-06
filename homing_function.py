import time 

from ai_class import Camera, Detection, ai_storage, Frame
from move import move_singleton 
from drone_state import drone_state, DroneStateForHoming

def homeing(camera:Camera,
            ai_frame:Frame,
            poss:DroneStateForHoming):

    if len(ai_frame.detection) == 0:
        return None

    # filter for the most confidnt det in the targeted objects 

    # TODO: remove person from this list THIS IS JUST FOR TESTING 
    targeted_obj = ["sports_ball","frisby","person"] 

    ai_frame_temp = []    
    for i in ai_frame.detection:
        if i.label in targeted_obj:
            ai_frame_temp.append(i)

    ai_frame.detection = ai_frame_temp

    max_conf = 0
    max_det = None
    for i in ai_frame.detection:
        if i.confidence > max_conf:
            max_conf = i.confidence
            max_det = i 

    frame = max_det
    if frame == None:
        return None
    
    dist_x_ned = Camera.y_dist_per_pix_per_meter * poss.altitude_rel_home * frame.get_the_vector_center()[1]  # Camera Y → Drone X
    dist_y_ned = -Camera.x_dist_per_pix_per_meter * poss.altitude_rel_home * frame.get_the_vector_center()[0]  # -Camera X → Drone Y
    
    move_singleton.send_displacement_command_yaw_stay_same(dist_x_ned,dist_y_ned,0)

    return dist_x_ned, dist_y_ned


if __name__ == "__main__":
    from telemetry import telemetry_singlton
    from move import move_singleton
    from drone_state import drone_state
    from ai_class import Camera

    telemetry_singlton.passer(move_singleton.passer)
    telemetry_singlton.passer(drone_state.passer)

    ai_storage.start_ai()
    # if input("do you want to do homing (y/n)") != "y": exit()
    loop_count = 0
    while True:
        loop_count += 1
        time.sleep(0.1)
        if not drone_state.enabel_homing_and_autonomy:
            if loop_count % 10 == 0:
                print("not running homing because swich not flipped")
            if move_singleton.get_mode() == "GUIDED":
                move_singleton.set_mode("POSHOLD")
            continue

        move_singleton.set_mode("GUIDED")
        if ai_storage.get_frame_array()[0] == None:
            print("ai frame is None continue")
            continue
        
        x_y_dist = homeing(Camera(),ai_storage.get_frame_array()[0],drone_state)
        print(f"running homing will move by {x_y_dist}")