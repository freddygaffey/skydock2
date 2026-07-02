import io
import threading
import time
import cv2

def app_runner(port=3,fsm=None):
    from flask import Flask, send_file
    from mission_logging import get_mission_dir
    from ai_class import ai_storage_singleton

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
         cv2.putText(imgcv,f"fps:{fps}",org=(20,20),fontScale=100,fontFace=cv2.FONT_HERSHEY_PLAIN,color=(250,225,100))

         cv2.putText(imgcv,f"{fsm.current_state}",org=(20,35),fontScale=100,fontFace=cv2.FONT_HERSHEY_PLAIN,color=(250,225,100))

         # draw bboxes from latest drone AI frame
         frame = ai_storage_singleton.get_latest_frame()
         if frame is not None and imgcv is not None:
             img_h, img_w = imgcv.shape[:2]
             # bbox coords are in frame pixel space; scale to actual image size
             sx = img_w / frame.width
             sy = img_h / frame.height
             for det in frame.detection:
                 (x0, y0), (x1, y1) = det.bbox
                 p0 = (int(x0 * sx), int(y0 * sy))
                 p1 = (int(x1 * sx), int(y1 * sy))
                 cv2.rectangle(imgcv, p0, p1, color=(0, 255, 0), thickness=2)
                 label = f"{det.label} {det.confidence:.2f}"
                 cv2.putText(imgcv, label, org=(p0[0], max(p0[1] - 5, 10)),
                             fontScale=1, fontFace=cv2.FONT_HERSHEY_PLAIN, color=(0, 255, 0))

         imgcv = cv2.resize(imgcv, None, fx=0.5, fy=0.5)
         ok, buf = cv2.imencode(".jpg",imgcv, [cv2.IMWRITE_JPEG_QUALITY,60])

         return send_file(io.BytesIO(buf.tobytes()),mimetype='image/jpeg')


    app.run(host='0.0.0.0', port=port)

