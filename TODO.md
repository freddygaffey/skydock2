# TODO

## Session handover — Aug 17 2026

State: everything is committed and pushed through `dbfa371`; CI (core +
log-server + SITL incl. the black-box full-mission test) was green on the
last full run. Working tree only has junk (.DS_Store, .next_mission_id).

First actions next session:
- RESTART the log server (two stale instances were fighting on port 5050 —
  kill both `tools/log_server/app.py` processes first). The restart picks up
  the perf overhaul (4.5-6.4x dashboard loads), newest-first mission lists,
  and the concurrent-index-build fix. All 80 RPi missions are synced into
  rpi_missions/ (the old logs/ duplicate tree was merged+verified+removed;
  pull_logs_rpi.sh deleted — tools/sync_rpi_logs.sh or the app's Sync RPi
  button is the one sync path, newest-first).

Open decisions (Fred):
- /summary + /timeline still full-scan big logs (~5 s on 847 MB): add derived
  columns to the index (schema bump, rebuilds sidecars) or a derived-payload
  sidecar? Design call needed.
- utils.detection_to_ned rebuilds 3 rotation matrices per call — ~0.9 s per
  16k-frame /frame_events, also flight-relevant. Fred's file; worth caching
  Rz@Ry@Rx per (roll,pitch,yaw).
- 1000 ms latency SITL validation never ran to completion with all fixes in
  (SIM_AI_LATENCY_MS currently 200): bump to 1000, run
  tests_sitl/test_z_full_mission.py, revert.
- rtl/daemon-thread shutdown discussion; scan clustering refactor + Frame
  snapshot design review (both parked, both working).
- Env: rogue sphinxcontrib_youtube 100.2.1 (dependency-confusion lookalike)
  still installed in user site-packages; uninstall+inspect pending.

## Two-model perception (scan vs homing) — discussed Aug 17, not implemented

Swap HEFs at the SCAN->GOTO boundary (phases are exclusive; no Hailo
multiplexing). Scan: yolov8n_1984 @ 24 fps (pixels-on-target is the binding
constraint; ~13 px @ 10 m; statistical floor ~5 fps from 5.2 s in-frame per
pass x MIN_NUM_DET). Homing: yolov8n_640 @ 40 fps camera-bound (416 is blind
past ~7 m which breaks climb-to-search; floor ~10 fps for control latency).
Camera mode 2028x1520@40 also restores full vertical FOV: cross-track
half-swath 2.8 m -> ~3.9 m (update SENSOR_H_PX 2160->3040 in drone_state.py
if adopted — interacts with mission_gen row spacing). Make sim_ai
imperfections per-phase when this lands.

## Show scan path + weed locations in Mission Planner before/during flight (Fred)

Update SCAN and GOTO so the ground station (Mission Planner) displays where the
drone will fly and where the weeds are — verify the plan on the map BEFORE the
mission starts, and watch weed locations appear during flight. Very useful for
in-field debugging and test days.

Sketch (not implemented yet — likely not complicated):
- On mission start: upload the scan waypoints to the FC as MAVLink mission
  items (MISSION_COUNT / MISSION_ITEM_INT protocol). Mission Planner draws
  whatever mission is on the vehicle, even though we fly GUIDED and never
  execute it. telemetry.py already has wp_q / get_auto_mission_wp machinery
  nearby.
- After scan clustering (and as GOTO targets each weed): push weed locations
  so they render on the map — options: append as mission items, rally points,
  or send named MAV_CMD/STATUSTEXT + use Mission Planner's POI. Pick whatever
  renders cleanest.
- Keep it read-only for the FC: the uploaded mission must never be executed
  (we stay in GUIDED); it is purely a display artifact.

## Parked / other
- goto + mission_gen overhaul (Fred) — includes fixing lawnmower row spacing:
  camera cross-track half-swath is ~2.8 m at 10 m alt, mission_gen default
  row_spacing_m=8 leaves blind lanes (see blackbox6.json which uses 4 m).
- rtl / clean process shutdown: daemonize telemetry passer + server threads so
  main.py exits after RTL without exit() hacks (discussion pending).
- homing latency compensation: detection_to_ned returns the offset from the
  capture-time position; subtract drone displacement since capture
  (gps_history dead-reckon) so the PID fights less delay (less fishbowl).
- discuss: states/scan.py clustering refactor + ai_class snapshot design
  (done, review together).
- verify real pipeline (detection_simple.py) attaches drone_state at capture
  time, not callback time — otherwise the latency pairing fix is sim-only.
