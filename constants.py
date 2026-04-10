#########################
# globa
# #######################
import sys
SIM_SPEED = int(sys.argv[sys.argv.index("--speedup") + 1]) if "--speedup" in sys.argv else (int(sys.argv[sys.argv.index("--speed") + 1]) if "--speed" in sys.argv else 1)


###########################
###### fsm ################
# Set from mission JSON params in main.py before FSM is imported
###########################

# Scan state
SCAN_HIGHT = None           # scan_height_m
SCAN_SPEED_MS = None        # scan_speed_ms
MIN_DIST_FROM_WAYPOINT = None  # min_dist_from_waypoint_m
MIN_WEED_SPACING = None     # min_weed_spacing_m
MIN_NUM_DET = None          # min_num_det

# Goto state
GOTO_ALT = None             # goto_alt_m

# Homing state
MAX_HOMING_DIST = None      # max_homing_dist_m
MIN_ALT = None              # min_alt_m

# Spray state
MIN_SPRAY_ERROR = None      # min_spray_error_m


###########################
###### sim ai #############
###########################

# False = perfect camera: every weed detected exactly, no false positives
# True  = realistic camera: pixel jitter, missed detections, false positives, wrong labels
SIM_AI_ENABLE_IMPERFECTIONS = True
