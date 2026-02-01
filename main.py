from ai_class import ai_storage_singleton
from telemetry import telemetry_singlton
import time

ai_storage_singleton.start_ai()
while True:
    frame = ai_storage_singleton.get_latest_frame()
    # for i in frame.detection:
        # print(i)
    print(telemetry_singlton.drone_state)
    time.sleep(0.1)