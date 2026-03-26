#!/bin/bash
# Usage: start_sitl.sh [speedup]
# e.g.   start_sitl.sh 10   → runs at 10x speed
SPEEDUP=${1:-1}
. venv-ardupilot/bin/activate
cd ~/ardupilot/ArduCopter
sim_vehicle.py -v ArduCopter -w --console --map \
  --out=tcp:127.0.0.1:5760 \
  --out=udp:127.0.0.1:14552 \
  --speedup="$SPEEDUP"