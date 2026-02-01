#!/bin/bash
# sync_to_rpi.sh

rsync -avz --delete \
    /home/fred/skydock2/ fred@rpi.local:~/skydock_2_laptop_sync/

ssh -t fred@rpi.local "cd ~/hailo-rpi5-examples/ && source setup_env.sh && cd ~/skydock_2_laptop_sync/ && export DISPLAY=:0 && bash"
