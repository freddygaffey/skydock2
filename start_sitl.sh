#!/bin/bash
. venv-ardupilot/bin/activate
cd ~/ardupilot/ArduCopter
sim_vehicle.py -v ArduCopter -w --console --map \
  --out=tcp:127.0.0.1:5760 \
  --out=udp:127.0.0.1:14552