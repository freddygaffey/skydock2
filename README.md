# skydock2

Autonomous agricultural spray drone. A Raspberry Pi 5 companion computer runs a
mission finite-state machine that scans a field with a Hailo AI camera, clusters
weed detections, then flies to and "sprays" each weed. Flight is executed by an
ArduPilot flight controller; the Pi talks to it over MAVLink (`pymavlink`).

The same code runs against ArduPilot **SITL** for development, with a simulated
camera (`sim_ai.py`) that projects known weed locations into synthetic detections.

## Stack

| Layer | What |
|-------|------|
| Flight controller | ArduPilot (Copter), MAVLink over serial (real) or UDP (sim) |
| Companion computer | Raspberry Pi 5 |
| AI camera | Hailo-8 on RPi5 (`hailo-rpi5-examples/`, vendored); sim equivalent in `sim_ai.py` |
| Language | Python 3 (numpy, pymavlink, pyserial, SQLAlchemy; Flask for the log viewer) |
| Persistence | Per-mission SQLite DB + `mission.jsonl` event log |

## Repository layout

| Path | Purpose |
|------|---------|
| [main.py](main.py) | Entry point: connect telemetry, load mission, run the FSM loop |
| [fsm.py](fsm.py) | `StateMachine` — dispatches per-tick to a state handler |
| [states/](states/) | One module per state: `override`, `scan`, `goto`, `homing`, `spray`, `rtl` (+ `enum`, `shared_data`) |
| [telemetry.py](telemetry.py) | MAVLink connection, background reader thread, movement commands |
| [drone_state.py](drone_state.py) | `DroneStateForHoming` telemetry snapshot + attitude/position interpolation |
| [ai_class.py](ai_class.py) | `Detection`, `Frame`, and the thread-safe `ai_storage_singleton` |
| [sim_ai.py](sim_ai.py) | Simulated camera: projects weed GPS to pixel detections |
| [utils.py](utils.py) | Pure geometry: haversine, pixel↔NED↔lat/lon projection |
| [DB.py](DB.py) / [DB_abstraction.py](DB_abstraction.py) | SQLAlchemy models and the high-level DB API |
| [mission_gen.py](mission_gen.py) | Build a lawnmower scan path / mission JSON from weed locations |
| [mission_logging.py](mission_logging.py) | Allocate `missions/NNNN/`, write `mission.jsonl` |
| [sitl.py](sitl.py) | Launch and configure ArduPilot SITL |
| [constants.py](constants.py) | Mission tunables (heights, speeds, thresholds, timeouts) |
| [tools/](tools/) | Offline analysis: `fsm_analyze`, `make_video`, `sim_accuracy`, and the Flask `log_server` mission viewer |
| [tests/](tests/) | Pytest suite (runs with no hardware/SITL) |
| [docs/](docs/) | Architecture, testing guide, SITL guide, code review, refactor plan |
| `archive/`, `hailo-rpi5-examples/` | Dead/experimental code and vendored Hailo examples (out of scope) |

See [docs/architecture.md](docs/architecture.md) for diagrams and data flow.

## Running in simulation

Requires Linux with ArduPilot SITL installed (`sim_vehicle.py` on PATH via
`~/venv-ardupilot`) and `xterm`. See [docs/skydock_sitl_guide.md](docs/skydock_sitl_guide.md)
for full setup.

```bash
pip install -r requirements.txt
python main.py --sim                 # default sim_data mission
python main.py --sim --speed 5       # 5x SITL speedup
```

`--sim` starts SITL, arms and takes off automatically, runs the simulated camera,
and drives the FSM. Mission artifacts are written to `missions/NNNN/`.

## Running on the real drone

On the Pi, with the flight controller connected over USB and the Hailo camera
pipeline available:

```bash
pip install -r requirements.txt
python main.py                       # prompts for a mission file, then takeoff
```

`main.py` lists existing `real_missions/*.json` or records a new one by walking
the drone over each weed and capturing GPS. Autonomy is gated by a 3-position RC
switch (channel 16). Battery / failsafe handling is delegated to the ArduPilot
flight controller: when the FC switches to RTL, the FSM detects `mode == "RTL"`
and stops.

## Mission artifacts

Each run creates `missions/NNNN/`:

| File | Contents |
|------|----------|
| `droneDB.db` | SQLite: waypoints, weeds, drone_states, detections |
| `mission.jsonl` | One JSON object per line: state transitions, telemetry samples, move commands, detections, spray events |
| `database_snapshot.json` | JSON dump of the DB written by `backup_and_clear` at mission load |

Review them with the log server: `python -m pytest`-free, run
`python tools/log_server/app.py` (needs `flask`).

## Tests

The flight-stack suite runs on a laptop — no drone, no SITL (telemetry is mocked,
the DB uses temp SQLite):

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest                                  # flight stack (tests/)
pip install flask && python -m pytest tools/log_server/tests/   # log viewer
```

See [docs/testing.md](docs/testing.md) for how the suite stubs hardware and how to
add tests for new states.

## More docs

- [docs/architecture.md](docs/architecture.md) — system diagram, FSM, homing flow, DB schema, design-vs-implementation drift
- [docs/testing.md](docs/testing.md) — test architecture and conventions
- [docs/skydock_sitl_guide.md](docs/skydock_sitl_guide.md) — SITL setup
- [docs/code_review_2026-06-13.md](docs/code_review_2026-06-13.md) — code review findings
- [docs/refactor_plan.md](docs/refactor_plan.md) — phased follow-up work
