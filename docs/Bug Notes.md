General notes and ToDos

1) Sometimes multiple scans are required. Address issue with

---

## BUG (2026-07-05, confirmed by code inspection): HOMING blind on real hardware — camera resolution metadata never reaches drone_state

**Symptom (real flights only):** in HOMING the drone does not lock onto a ball
directly underneath it; it drifts, loses the detection, climbs to search, and
eventually times out (`homing_give_up_no_det` / `homing_give_up_timeout`).
Sim is unaffected.

**Root cause — stale singleton name in the real AI callback:**
`hailo-rpi5-examples/basic_pipelines/detection_simple.py:132` (the
`ai_callback.py` symlink target) pushes the live camera resolution into
telemetry with:

    ts = getattr(telemetry, "telemetry_singlton", None)   # <-- old typo name
    if ts is not None:
        ts.drone_state.width = width
        ts.drone_state.height = height

Commit `e220b46` (2026-06-16, "typo rename") renamed the singleton to
`telemetry_singleton` in skydock2, but `detection_simple.py` lives in the
nested hailo-rpi5-examples repo and was missed. Since then `getattr` returns
`None` and the resolution write is silently skipped — the classic failure mode
of a `getattr(..., None)` guard.

**Why that breaks homing:** the real pipeline's lores stream now runs at
640x640 (confirmed: recent saved frame `logs/1776121207444129879.jpg` is
640x640; the May-era flights, e.g. `logs/0063/frames/*.jpg`, were 1280x1280).
The callback emits detection bboxes in 640-space pixels, but
`DroneStateForHoming` keeps its defaults `width = height = 1280`
(`drone_state.py:72-73`), and `utils.detection_to_ned()` builds its intrinsics
(fx, fy, cx, cy) from those fields. So every real detection is projected with
cx,cy = (640,640) — the bottom-right CORNER of the actual image — and focal
lengths 2x too long.

**Quantified effect** (ball dead-centre under the drone, det centre = (320,320)
in 640-space, FOV 55.3 x 31.2 deg):

    alt  5 m -> phantom offset N=-1.31 E=-0.70  (dist 1.48 m)
    alt 10 m -> phantom offset N=-2.62 E=-1.40  (dist 2.97 m)
    alt 15 m -> phantom offset N=-3.93 E=-2.09  (dist 4.45 m)

A perfectly-centred ball reads as ~3 m away (> MIN_SPRAY_ERROR = 2.0) so the
spray gate can never pass at working altitude; homing chases a phantom point
up-and-left in the image, equilibrium only exists with the ball at the image
corner, the detection drops out, the no-det branch climbs, and the phantom
offset grows with altitude — runaway until timeout. Matches the reported
behaviour exactly.

**Why sim never catches it (the "divergent branch"):** `sim_ai.py:283-284`
sets `ds.width`/`ds.height` itself from the shared camera model, so the sim
path always has consistent resolution metadata. Only the real callback relies
on the broken write. (Suspicion #1 confirmed; no evidence of a sign error in
states/homing.py — its control law and detection_to_ned round-trip are covered
by tests and mutation-checked. Camera-mount axis convention remains unverified
by logs and still needs the calibration flight, but it is not needed to explain
this symptom.)

**Related latent issues in the same area (found during analysis):**
- `ai_class.py` `Frame.__init__` hardcodes `self.height = self.width = 1280`;
  `server.py` scales bbox overlays by `img_w / frame.width`, so on a 640x640
  stream the drawn boxes are at half scale / wrong position. Display-only, but
  misleading when field-debugging exactly this bug.
- `server.py` `fontScale=100` (commit f3a2c0c) makes the fps/state text
  unreadable — looks like a debug leftover.

**Proposed fix (not yet applied — Fred to approve scope):**
1. In `detection_simple.py`, use the current name (`telemetry_singleton`), and
   fail LOUDLY (log/print once) if the telemetry module/singleton is absent,
   so a future rename can't silently disable the write again.
2. Prefer carrying resolution WITH the data instead of via side-channel:
   set `frame.width/height` from the GStreamer caps in the callback and make
   `detection_to_ned()` take resolution from the frame (or stamp the Frame's
   drone_state), eliminating the shared-mutable-state hop entirely.
3. Change the `drone_state.py` defaults to 640x640 (the real lores size) so a
   missed write fails toward reality, and add a startup assertion/log of the
   active resolution.
4. Regression test: real-callback-shaped Frame (640-space detections) +
   default drone_state must project a centred detection to ~(0,0) NED. 