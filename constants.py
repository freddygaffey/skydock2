#########################
# globa
# #######################
import sys
SIM_SPEED = int(sys.argv[sys.argv.index("--speed") + 1]) if "--speed" in sys.argv else 1


###########################
###### fsm ################
###########################

# Scan state constants
SCAN_HIGHT = 50  # m
MIN_DIST_FROM_WAYPOINT = 8  # m
MIN_WEED_SPACING = 2  # m
MIN_NUM_DET = 3

# Goto state constants
GOTO_ALT = 10  # m
LAST_GO_TO_TIME = 0

# Homing state constants
MAX_HOMING_DIST = 10  # m
MIN_ALT = 5  # m

# Spray state constants
MIN_SPRAY_ERROR = 2  # m

last_det_time = 0


###########################
###### sim ai #############
###########################

# False = perfect camera: every weed detected exactly, no false positives
# True  = realistic camera: pixel jitter, missed detections, false positives, wrong labels
SIM_AI_ENABLE_IMPERFECTIONS = False
