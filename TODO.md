# TODO

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
