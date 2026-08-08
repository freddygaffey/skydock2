"""Mission tunables. Distances in metres, speeds in m/s, times in seconds.

SIM_SPEED is the SITL speedup factor, parsed from argv at import (1 on real
hardware). Homing timeouts are divided by it so they fire in wall-clock terms.
"""

#########################
# global
#########################
import sys
SIM_SPEED = int(sys.argv[sys.argv.index("--speedup") + 1]) if "--speedup" in sys.argv else (int(sys.argv[sys.argv.index("--speed") + 1]) if "--speed" in sys.argv else 1)


###########################
###### fsm ################
###########################

# Scan state
SCAN_HEIGHT = 10
SCAN_SPEED_MS = 2
MIN_DIST_FROM_WAYPOINT = 1.0
MIN_WEED_SPACING = 2.0
MIN_NUM_DET = 3

# Goto state
GOTO_ALT = 5

# Homing state
MAX_HOMING_DIST = 10 
MIN_ALT = 3
MAX_HOMING_ALT = 30

# Spray state
MIN_SPRAY_ERROR = 2.0

# Homing timeouts (real-time seconds; states/homing.py divides by SIM_SPEED)
TIME_WAIT_FOR_DET = 1000
MAX_HOMING_TIME = 1000


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

# When True, sim_ai renders a synthetic camera frame each tick and saves it to
# missions/NNNN/frames/{time_ns}.jpg — the same path/naming the real pipeline uses —
# so sim and real share one image code path (camera stream, make_video, log_server,
# training tooling). The frame shows the ground, true weeds, predicted (clustered)
# weeds, and the detection boxes. Set False to skip rendering (saves Pi/CPU).
SIM_AI_RENDER_FRAMES = True

# Side length (px) of the saved JPEG. The real lores stream is 640. 0 = render at the
# full sim resolution (DroneStateForHoming.width/height) with no downscale.
SIM_AI_RENDER_SIZE = 640

# Max JPEGs saved per second of SIMULATED time. The sim loop runs at TARGET_FPS (30),
# so saving every frame makes a long mission produce >100k JPEGs — slow to turn into a
# video and heavy on disk. Saving a handful per sim-second is plenty for a review video
# / camera stream. Set >= TARGET_FPS to save every frame.
SIM_AI_RENDER_MAX_FPS = 100
