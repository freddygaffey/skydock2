# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Code ownership (agreed Aug 16, 2026 — MUST follow)

FRED'S FILES — never edit without an explicit ask for that specific change.
When work reveals a needed change here, report the finding with the exact
file:line and the suggested replacement, and let Fred apply it:
  telemetry.py, drone_state.py, ai_class.py, ai_callback.py /
  detection_simple.py, constants.py, utils.py, fsm.py, states/* (all state
  files), main.py, mission_gen.py, server.py, preflight_tests.py,
  .github/workflows/ (CI — Fred is learning it; explain, don't do)

COLLABORATIVE — propose scope first, implement only after Fred agrees:
  DB.py, DB_abstraction.py, mission_logging.py, sim_ai.py,
  sim_data/ + real_missions/ (Fred owns real mission data; Claude may add sim
  fixtures for tests), tools/push_real_missions.sh,
  CLAUDE.md + .gitignore

CLAUDE'S FILES — act autonomously, keep tests green, report what changed:
  tools/ (including tools/log_server — "the website"), sitl.py, tests/,
  tests_sitl/, tools/log_server/tests/, requirements*.txt

Generated output (missions/, logs/) — nobody hand-edits.

Cross-boundary rule: a failing test caused by Fred's files is a REPORT, not a
fix. Diagnose, point at the line, hand it over.

An explicit command from Fred ("set MIN_NUM_DET to 5", "set the latency to
1000 and test") IS authorization to edit his files directly for that change —
no ceremony needed. Beyond the exact commanded change, ask; he'll often agree
unless the change is invasive or bloated.

## Teaching mode (MUST follow)

The goal is that Fred learns, not that Claude does everything. When a change
is instructive or interesting — new concept, a bug worth understanding, code
in or near Fred's files — explain the why, point at file:line with a concrete
suggestion, and let Fred type it (the scan.py:35 pattern). Reserve
just-doing-it for mechanical/boring work in Claude's files. Fred can always
override with "just do it" (or similar) when he can't be bothered — then do
it without ceremony.

Fred wants to follow best practices: when his code or approach deviates from
one, SAY SO — unprompted, candidly, with the reason and the conventional
alternative. Ownership limits who edits, never who critiques. The decision
stays his; silence is not deference, it's a disservice.

Fred does not always read responses thoroughly. If he doesn't react to a
finding, question, or suggestion, that is NOT a "no" — it may simply be
unread. Re-raise important open items (briefly, not naggingly) at natural
moments until they get an actual yes/no; keep a short "open items" note at
the end of a long reply so nothing important is buried mid-text.

Sometimes (not always) have Fred run the tests himself — hand him the exact
command and let him execute and read the result, so the test workflow becomes
his muscle memory too. Good moments: after HE edited the code under test, or
when a run's output is worth him seeing raw. Claude still runs tests
routinely when verifying its own changes.

## Sim-to-real unification — status (June 11, 2026)

Goal: unify sim and real code paths, then a testing ladder, then a constant-tuning procedure.
Fred owns all design decisions — propose scope before changing anything, especially flight logic.

Done (uncommitted work in tree: constants.py, sim_ai.py, detection_simple.py, tests/):
- Camera model unified: sim_ai derives FOV/intrinsics AND resolution from DroneStateForHoming
  (drone_state.py is the single source of truth for all camera properties). Committed in 96aa2ae.
- constants_snapshot event logged at mission start (main.py).
- TARGET_FPS moved to constants.py, shared by sim_ai and ai_callback (ai_callback.py is a
  symlink to hailo-rpi5-examples/basic_pipelines/detection_simple.py — edit the target).
- Sim detections now routed through Frame.add_detection (same label gate as real pipeline);
  sim false positives labelled "sports ball" (only FP kind that survives the gate).
- tests/test_sim_ai.py de-stubbed: uses real ai_class/drone_state/constants. Test env:
  ~/.pyenv/versions/3.10.18 (pytest). Beware stale __pycache__ on weird failures.
  Current counts: tests/ = 165, tools/log_server/tests/ = 27 (incl. Playwright E2E). All pass.

## Testing policy (MUST follow)

- ALWAYS run the relevant test suite after adding or changing a feature and confirm it
  passes BEFORE telling the user it's done. Never report a change complete without a green run.
    - Core: `python3 -m pytest tests/ -q`
    - Log server (incl. Playwright E2E): `python3 -m pytest tools/log_server/tests/ -q`
- WHEN ADDING A FEATURE, ADD TESTS FOR IT in the same change — enough that a regression
  would fail a test. More tests are better; the user explicitly wants breakage to surface.
    - Backend/logic → pytest (Flask test client for log_server endpoints; assert payload
      shape AND size bounds, not just status codes — see tools/log_server/tests/
      test_frame_events_payload.py).
    - Dashboard/UI behaviour → Playwright E2E in tools/log_server/tests/test_dashboard_e2e.py
      (drives real headless Chromium against a live server; catches JS errors the Flask
      client can't). Browser binary: `python3 -m playwright install chromium` (one-time;
      the E2E module skips cleanly if it's missing). Use `python3` (has playwright+flask),
      not `~/.pyenv/versions/3.10.18/bin/python` (no playwright).
    - SITL integration → `python3 -m pytest tests_sitl/ -q` (~2 min; NOT part of the fast
      suite). Boots a headless SITL via ~/venv-ardupilot (or reuses one on udp:14550;
      skips cleanly if ArduPilot/venv missing). Covers telemetry readiness, the measured
      sim_speed estimator, arm+takeoff, and GUIDED velocity motion.
- If a feature is hard to test, say so explicitly rather than skipping silently.

Logging overhaul — DONE (schema v2, June 13 2026):
- mission_logging.py rewritten. log_event takes RAW project objects (DroneStateForHoming,
  Frame, Detection, DroneStateEnum); ALL formatting lives in mission_logging via type-aware
  encoders, so call sites stay terse. Canonical envelope (time_ns + ts + level + logger + event)
  injected centrally — producers no longer pass timestamps. Enums encode to .name (no more
  "DroneStateEnum.SCAN" leak). drone_state on disk is an explicit projection (no reflective
  vars()); the dataclass's `rotaion` typo is corrected to `rotation` on disk only.
- EVENTS registry in mission_logging.py lists every valid event; unregistered names warn.
  mission_logging.iter_events is the ONE reader — surfaces malformed lines (no silent drop).
  Clean break: schema_version=2; old (v1) logs are NOT back-compat.
- Contract test tests/test_log_contract.py STOPS regressions: AST-scans producers (every emitted
  event must be in EVENTS; no str(enum) on state kwargs; canonical level spellings) + encoder/
  envelope round-trip. If you add an event, register it in EVENTS or the test fails.
- Call sites: fsm.py passes raw enums; homing.py uses WARNING (not WARN).
- Tools migrated to the shared reader + clean field names (deleted the DroneStateEnum/rotaion
  cruft). sim_accuracy.py had real bugs fixed (read nested weed{}, dict weed_locations).
- log_server fixes: index builder uses a single-file rollback journal (WAL + atomic-rename was
  orphaning data → "not built"/disk-I/O-error); build endpoint returns JSON on any error;
  projection FOV now comes from drone_state (was ~18.8deg from image width; real 55.3x31.2);
  scan_height_m default 35->10; default port 5050 (macOS AirPlay owns 5000).
- Still deferred: CONSOLE logging (scattered print() -> stdlib logging to console +
  missions/NNNN/console.log). The fsm.py `print(self.current_state)` enum spam lives there.

In progress — mutation-testing audit of tests (verify tests catch real bugs, not just pass):
planned mutations: M1 swap N/E in detection_to_ned; M2 drop cos(lat) in detection_to_latlon;
M3 change rotation order Rz@Ry@Rx in BOTH utils functions (predict: test_geometry_math's own
round-trip cancels and passes — self-inverse blind spot — but tests/test_projection_roundtrip.py
catches it via sim_ai); M4 scan.py `< MIN_NUM_DET` → `<=`; M5 widen MIN_WEED_SPACING merge.
Procedure: one mutation at a time, run pytest tests/, expect failure, revert, confirm clean diff.

Remaining unification decisions (Fred's call):
- Sim resolution 1280 vs 640 (real lores stream is 640x640) — now one edit in drone_state.py.
- tools/test_camera_orientation.py still has stale 27.4/21 deg FOV constants.

Next phases: testing ladder (SITL Monte Carlo scorecard via tools/sim_accuracy.py, bench
perception test to MEASURE real miss-rate/jitter/FP-rate, walk test, constrained flights),
then tune: physical constants measured once; perception constants tuned offline from recordings;
control constants tuned in noise-calibrated sim then verified one-change-per-flight.
Deferred: console logging (print -> stdlib; see Logging overhaul above). Parked: replay mode.

## What this project is

Skydock2 is an autonomous drone controller for weed detection and spraying. It runs on a Raspberry Pi 5 with a Hailo AI accelerator attached to a drone running ArduPilot. In simulation it uses ArduPilot SITL instead of real hardware.

The system:
1. Scans a field at altitude using a lawnmower path, collecting weed detections from the camera
2. Clusters detections into weed locations
3. Flies to each weed (GOTO state), homes precisely over it (HOMING state), and sprays (SPRAY state)
4. Returns to launch when done

## Running

**Simulation (primary dev workflow):**
```bash
python main.py -s                        # run first JSON file found in sim_data/
python main.py -s sim_data/0010.json     # run a specific sim file
python main.py -s --speedup 10           # run at 10× speed
```

The sim launcher starts ArduPilot SITL automatically in an `xterm` window (requires `xterm` and ArduPilot installed at `~/ardupilot/`). SITL listens on UDP port 14550. If SITL is already running on that port it is reused.

**Real hardware:**
```bash
python main.py                           # connects to FC on /dev/ttyACM0 or /dev/ttyACM1
```

On real hardware `main.py` prompts for a mission file name. If the file exists in `real_missions/` it is loaded directly; otherwise it walks you through marking weed locations using live GPS, saves a new mission file, then starts the FSM.

**Tests:**
```bash
python tests/test_sim_ai.py
```

**Standalone tools:**
```bash
python tools/sim_accuracy.py <missions/NNNN/mission.jsonl>   # post-mission accuracy report
python tools/make_video.py <missions/NNNN/>                   # render mission video
python tools/fsm_analyze.py <missions/NNNN/mission.jsonl>     # FSM state timeline
tools/push_real_missions.sh                                    # sync real_missions/ to remote RPi
python tools/log_server/                                       # web log viewer (Flask)
```

## Architecture

### Entry point — `main.py`
Parses CLI flags, starts SITL if in sim mode, initialises telemetry, sets up the per-mission directory (`missions/NNNN/`), then starts the FSM loop at ~30 FPS (scaled by `SIM_SPEED`).

### State machine — `fsm.py` → `states/`
`StateMachine.update()` is called every loop tick. States:
- `OVERRIDE` – FC not in GUIDED or autonomy disabled; does nothing
- `SCAN` – flies waypoints from DB, logs frames; on completion runs `prosess_all_scan_data()` which clusters detections into weed locations
- `GOTO` – flies to the closest unsprayed weed
- `HOMING` – fine-positions the drone directly over the weed using camera feedback
- `SPRAY` – activates sprayer, marks weed sprayed
- `RTL` – FC switched to RTL; FSM exits

`_overide_and_rtl_checks()` runs on every tick and can override any state.

### Telemetry — `telemetry.py`
Singleton `telemetry_singlton`. Connects to FC via pymavlink. Background thread populates `drone_state` (a `DroneStateForHoming`) from MAVLink messages at ~35 Hz. Exposes movement commands (`fly_to_point`, `send_displacement_command_yaw_stay_same`, `move_volocity_until_stop_or_max_time`). Velocity commands must be re-sent periodically; `move_volocity_until_stop_or_max_time` handles this on a thread.

### AI / camera — `ai_class.py`, `ai_callback.py`, `sim_ai.py`
Singleton `ai_storage_singleton` holds the latest `Frame` (list of `Detection`s). In simulation, `sim_ai.run_sim_ai()` generates synthetic detections at 30 FPS using camera projection math. On real hardware, `ai_callback.py` uses a GStreamer pipeline through a Hailo NPU.

`Frame.add_detection()` filters labels — only `sports ball`, `frisbee`, and `person` are kept (these are stand-ins for weed labels in testing).

### Database — `DB.py` (SQLAlchemy models) + `DB_abstraction.py` (high-level API)
SQLite database at `missions/NNNN/droneDB.db`. Key tables: waypoints, weeds, drone_states, detections. `db_abstraction` is a module-level singleton; `set_db_path()` must be called before importing `DB_abstraction`.

### Mission logging — `mission_logging.py`
Writes newline-delimited JSON to `missions/NNNN/mission.jsonl`. Every significant event (FSM transitions, move commands, weed detections, DB mutations, telemetry samples) is logged. `configure_mission_dir()` + `init_mission_log()` must be called before `log_event()`.

### Mission files — `sim_data/*.json`
Each file defines:
```json
{
  "weed_locations": [{"id": 0, "lat": ..., "lon": ...}, ...],
  "scan_path": [[lat, lon], ...]
}
```
Generated by `mission_gen.py` (lawnmower path bounding the weed locations).

### Constants — `constants.py`
Reads `--speedup` / `--speed` from `sys.argv` at import time — import order matters. Key values: `SCAN_HIGHT` (10 m — detections were unreliable at 35 m), `SCAN_SPEED_MS` (1.0 m/s), `MIN_WEED_SPACING` (2 m), `MIN_NUM_DET` (3 detections to confirm a weed). `SIM_AI_ENABLE_IMPERFECTIONS` toggles realistic camera noise.

### Coordinate math — `utils.py`
`detection_to_latlon()` and `detection_to_ned()` back-project a pixel detection to a GPS coordinate using drone attitude (roll/pitch/yaw from `DroneStateForHoming.rotaion`). Camera FOV constants must stay in sync between `sim_ai.py` and `utils.py`.

## Key singletons and initialisation order

```
constants (parse argv) → DB.set_db_path() → DB_abstraction (imports DB) →
telemetry_singlton → mission_logging.configure_mission_dir() →
mission_logging.init_mission_log() → ai_storage_singleton → StateMachine
```

Importing out of order (especially `DB_abstraction` before `set_db_path`) causes the DB to open in the wrong location.

