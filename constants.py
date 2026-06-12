#########################
# global
#########################
import sys
SIM_SPEED = int(sys.argv[sys.argv.index("--speedup") + 1]) if "--speedup" in sys.argv else (int(sys.argv[sys.argv.index("--speed") + 1]) if "--speed" in sys.argv else 1)


###########################
###### fsm ################
###########################

# Scan state
SCAN_HIGHT = 10
SCAN_SPEED_MS = 2
MIN_DIST_FROM_WAYPOINT = 1.0
MIN_WEED_SPACING = 2.0
MIN_NUM_DET = 3

# Goto state
GOTO_ALT = 5

# Homing state
MAX_HOMING_DIST = 3
MIN_ALT = 5
MAX_HOMING_ALT = 30

# Spray state
MIN_SPRAY_ERROR = 2.0

# Homing timeouts (real-time seconds; states/homing.py divides by SIM_SPEED)
TIME_WAIT_FOR_DET = 30
MAX_HOMING_TIME = 60


###########################
###### camera #############
###########################

# Frame rate for both the real pipeline (ai_callback) and the sim AI (sim_ai).
TARGET_FPS = 30


###########################
###### sim ai #############
###########################

# False = perfect camera: every weed detected exactly, no false positives
# True  = realistic camera: pixel jitter, missed detections, false positives, wrong labels
SIM_AI_ENABLE_IMPERFECTIONS = True
