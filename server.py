import io
import threading
import time
import cv2

PAGE = """<!doctype html>
<html>
<head>
<title>skydock live</title>
<style>
  body { background:#111; color:#eee; font-family:monospace; text-align:center; margin:0; padding:10px; }
  #controls { margin-bottom:10px; font-size:22px; }
  #fpsnum {
    width:100px; height:42px; font-size:24px; text-align:center;
    background:#222; color:#eee; border:2px solid #555; border-radius:6px;
  }
  #fps {
    -webkit-appearance:none; appearance:none;
    width:90%; max-width:900px; height:18px; margin:10px 0;
    background:#333; border-radius:9px; display:block;
    margin-left:auto; margin-right:auto;
  }
  #fps::-webkit-slider-thumb {
    -webkit-appearance:none; appearance:none;
    width:36px; height:36px; border-radius:50%;
    background:#3fa34d; border:3px solid #eee; cursor:pointer;
  }
  #fps::-moz-range-thumb {
    width:36px; height:36px; border-radius:50%;
    background:#3fa34d; border:3px solid #eee; cursor:pointer;
  }
  #actual { font-size:18px; color:#aaa; margin-left:15px; }
  .hint { font-size:14px; color:#777; margin-top:4px; }
</style>
</head>
<body>
  <div id="controls">
    <label>fps:</label>
    <input id="fpsnum" type="number" min="0.25" max="30" step="0.25" value="5">
    <span id="actual"></span>
    <input id="fps" type="range" min="0.25" max="30" step="0.25" value="5">
    <div class="hint">&uarr;/&darr; = &plusmn;1 fps &nbsp; shift+&uarr;/&darr; = &plusmn;0.25 fps (works anywhere on the page)</div>
  </div>
  <img id="view" style="max-width:100%">
  <script>
    const img = document.getElementById('view');
    const slider = document.getElementById('fps');
    const num = document.getElementById('fpsnum');
    const actual = document.getElementById('actual');
    let last = performance.now();

    slider.oninput = () => { num.value = slider.value; };
    num.oninput = () => { slider.value = num.value; };

    function targetFps() {
      const v = parseFloat(num.value);
      return (isNaN(v) || v < 0.25) ? 0.25 : v;
    }

    function setFps(v) {
      v = Math.min(30, Math.max(0.25, Math.round(v * 4) / 4));
      num.value = v;
      slider.value = v;
    }

    // global keybinding: works even when nothing is focused
    document.addEventListener('keydown', (e) => {
      if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
      e.preventDefault();  // also stops the number input double-stepping
      const step = e.shiftKey ? 0.25 : 1;
      setFps(targetFps() + (e.key === 'ArrowUp' ? step : -step));
    });

    function schedule() {
      setTimeout(tick, 1000 / targetFps());
    }

    function tick() {
      const loader = new Image();
      loader.onload = () => {
        img.src = loader.src;
        const now = performance.now();
        actual.textContent = 'actual: ' + (1000 / (now - last)).toFixed(1) + ' fps';
        last = now;
        schedule();
      };
      // frame not ready yet (e.g. mission just started) - retry slowly
      loader.onerror = () => setTimeout(tick, 1000);
      loader.src = '/frame.jpg?t=' + Date.now();
    }

    tick();
  </script>
</body>
</html>
"""

def _overlay_font(img_h):
    """Overlay text sized relative to the image (~14-16pt-on-A4 equivalent).

    Cap height ~1.8% of image height; HERSHEY_SIMPLEX caps are ~22 px at
    fontScale=1. Returns (fontScale, thickness, line_height_px).
    """
    cap_px = max(10.0, img_h * 0.018)
    return cap_px / 22.0, max(1, round(cap_px / 12)), int(cap_px * 1.6)


def create_app(fsm=None):
    from flask import Flask, send_file

    app = Flask(__name__)
    last_called = [0]

    @app.get("/")
    def main():
        return PAGE

    @app.get("/frame.jpg")
    def frame():
         from mission_logging import get_mission_dir

         diff = time.time() - last_called[0]
         fps = round(1/diff,2)
         last_called[0] = time.time()

         dir = get_mission_dir()
         path = f"{dir}/frames/latest.jpg"

         imgcv = cv2.imread(path)
         if imgcv is None:
             return "no frame yet", 503

         img_h, img_w = imgcv.shape[:2]
         fscale, fthick, line_h = _overlay_font(img_h)
         margin = max(8, line_h // 2)
         hud = (250, 225, 100)

         cv2.putText(imgcv, f"fps:{fps}", org=(margin, line_h), fontScale=fscale,
                     fontFace=cv2.FONT_HERSHEY_SIMPLEX, color=hud, thickness=fthick)

         state = fsm.current_state if fsm is not None else "?"
         cv2.putText(imgcv, f"{state}", org=(margin, 2 * line_h), fontScale=fscale,
                     fontFace=cv2.FONT_HERSHEY_SIMPLEX, color=hud, thickness=fthick)

         # frame + drone_state come off the fsm (stashed there each tick for us)
         # so this server never touches the flight singletons directly
         ai_frame = fsm.frame if fsm is not None else None
         ds = fsm.drone_state if fsm is not None else None

         if ds is not None:
             speed = (ds.velocity_x**2 + ds.velocity_y**2) ** 0.5
             telem = f"{ds.mode} alt:{ds.altitude_rel_home:.1f}m spd:{speed:.1f}m/s hdg:{ds.heading:.0f}"
             cv2.putText(imgcv, telem, org=(margin, 3 * line_h), fontScale=fscale,
                         fontFace=cv2.FONT_HERSHEY_SIMPLEX, color=hud, thickness=fthick)

         if ai_frame is not None:
             # bbox coords are in the AI frame's pixel space; scale to this image.
             # A frame of unknown size (width/height None) is assumed same-size.
             sx = img_w / ai_frame.width if getattr(ai_frame, "width", None) else 1.0
             sy = img_h / ai_frame.height if getattr(ai_frame, "height", None) else 1.0
             for det in ai_frame.detection:
                 (x0, y0), (x1, y1) = det.bbox
                 p0 = (int(x0 * sx), int(y0 * sy))
                 p1 = (int(x1 * sx), int(y1 * sy))
                 cv2.rectangle(imgcv, p0, p1, color=(0, 255, 0), thickness=2)
                 label = f"{det.label} {det.confidence:.2f}"
                 cv2.putText(imgcv, label, org=(p0[0], max(p0[1] - line_h // 4, line_h)),
                             fontScale=fscale, fontFace=cv2.FONT_HERSHEY_SIMPLEX,
                             color=(0, 255, 0), thickness=fthick)

         imgcv = cv2.resize(imgcv, None, fx=0.5, fy=0.5)
         ok, buf = cv2.imencode(".jpg",imgcv, [cv2.IMWRITE_JPEG_QUALITY,60])

         resp = send_file(io.BytesIO(buf.tobytes()),mimetype='image/jpeg')
         resp.headers["Cache-Control"] = "no-store"
         return resp

    return app

def app_runner(port=3,fsm=None):
    app = create_app(fsm=fsm)
    app.run(host='0.0.0.0', port=port)


def find_latest_mission_with_frames(missions_root="missions"):
    # prefer the newest REAL mission; fall back to newest sim one
    import json
    from pathlib import Path

    def is_real(mission_dir):
        try:
            with open(mission_dir / "mission.jsonl") as fh:
                return json.loads(fh.readline()).get("is_sim") is False
        except (OSError, ValueError):
            return False

    dirs = [p.parent.parent for p in sorted(Path(missions_root).glob("*/frames/latest.jpg"))]
    if not dirs:
        return None
    real = [d for d in dirs if is_real(d)]
    return (real or dirs)[-1]


if __name__ == "__main__":
    # standalone viewer: serve the frames of an existing mission dir
    # (no fsm / telemetry needed - state shows "?" and bboxes only if the
    # ai singleton is fed, which it isn't standalone)
    import argparse
    import sys
    from pathlib import Path
    from mission_logging import configure_mission_dir

    parser = argparse.ArgumentParser(description="view frames from a mission dir in the browser")
    parser.add_argument("mission_dir", nargs="?",
                        help="missions/NNNN dir (default: newest one with frames/latest.jpg)")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    mission_dir = Path(args.mission_dir) if args.mission_dir else find_latest_mission_with_frames()
    if mission_dir is None:
        sys.exit("no missions/*/frames/latest.jpg found - pass a mission dir explicitly")
    if not (mission_dir / "frames" / "latest.jpg").exists():
        sys.exit(f"{mission_dir}/frames/latest.jpg does not exist")

    configure_mission_dir(mission_dir)
    print(f"serving {mission_dir} -> http://localhost:{args.port}/")
    app_runner(port=args.port, fsm=None)
