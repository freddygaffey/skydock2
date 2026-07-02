import io
import threading
import time
import cv2

def app_runner(port=3,fsm=None):
    from flask import Flask, send_file
    from mission_logging import get_mission_dir

    app = Flask(__name__)
    last_called = [0]
    @app.get("/")
    def main():
         diff = time.time() - last_called[0]
         fps = round(1/diff,2) 
         last_called[0] = time.time()

         dir = get_mission_dir()
         path = f"{dir}/frames/latest.jpg"

         imgcv = cv2.imread(path)
         cv2.putText(imgcv,f"fps:{fps}",org=(20,20),fontScale=1,fontFace=cv2.FONT_HERSHEY_PLAIN,color=(250,225,100))

         cv2.putText(imgcv,f"{fsm.current_state}",org=(20,35),fontScale=1,fontFace=cv2.FONT_HERSHEY_PLAIN,color=(250,225,100))

         ok, buf = cv2.imencode(".jpg",imgcv)
         return send_file(io.BytesIO(buf.tobytes()),mimetype='image/jpeg')


    app.run(host='0.0.0.0', port=port)

