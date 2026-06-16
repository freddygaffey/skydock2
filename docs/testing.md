# Testing guide

The flight-stack test suite runs anywhere — no drone, no flight controller, no
SITL. Hardware modules are stubbed, the AI source is bypassed, and the database
uses a throwaway SQLite file per test.

## Running

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest                  # the flight-stack suite (tests/)
```

`pytest.ini` restricts collection to `tests/` and excludes `archive/`,
`hailo-rpi5-examples/`, and `tools/` (the last has its own suite). The log viewer
tests run separately and need Flask:

```bash
pip install flask
python -m pytest tools/log_server/tests/
```

## Why stubbing is needed

The flight stack binds its collaborators **by name at import time**:

```python
# states/scan.py
from telemetry import telemetry_singleton
from DB_abstraction import db_abstraction
from mission_logging import log_event
```

Importing `telemetry` for real would try to open a serial port; importing
`DB_abstraction` instantiates a real `DBAbstraction()` (and thus a SQLite engine)
at module load. So tests either:

1. **Stub the module in `sys.modules` before importing the code under test**, or
2. Use the real module but **patch the consuming module's attribute** (never the
   source) — because the consumer holds its own binding.

```python
# Patch where the name is USED, not where it is defined:
monkeypatch.setattr(states.scan, "db_abstraction", fake_db)   # correct
monkeypatch.setattr(DB_abstraction, "db_abstraction", fake_db)  # has no effect on scan
```

## Shared helpers

### `tests/conftest.py`
- **Import-time DB guard** — points `DB` at a temp path during collection, so no
  test run can ever create a stray `droneDB.db` in the repo.
- Factories: `make_drone_state`, `make_detection`, `make_frame`.
- `fake_telemetry`, `fake_db` — recording stand-ins (`tests/support.py`).
- `fresh_db` — a real `DBAbstraction` backed by a temp SQLite file, with the
  `DatabaseSession` singleton reset around the test.
- `reset_state_globals` — clears module-level FSM/AI state (homing timers, the
  scan "processed" latch, `shared_data`, the AI singleton).
- `constants_guard` — snapshot/restore `constants` for tests that mutate tunables.

### `tests/support.py`
- `ensure_stub_module` / `ensure_real_module` — install a stub, or evict a stub a
  sibling test left in `sys.modules` and import the real module. This is what
  makes the suite **order-independent** despite the shared `sys.modules` namespace.
- `FakeTelemetry`, `FakeDB` — record commands / serve canned data.
- `heartbeat_msg`, `global_position_msg`, `attitude_msg`, … — fake MAVLink
  messages (duck-typed `SimpleNamespace`) in raw wire units.
- `_StopLoop` — raise from a mock to break an otherwise infinite loop under test.

## Ordering hazards (and how the suite avoids them)

Because `sys.modules` is shared across the session:
- A test that stubs `mission_logging`/`telemetry` must do so **conditionally**
  (only if not already imported) or it will clobber the real module for later
  tests. The `if name not in sys.modules` pattern in `test_geometry_math.py` and
  `ensure_real_module` in `test_db_layer.py` / `test_safe_fixes.py` cooperate to
  keep this safe.
- `test_sim_ai.py` sets `constants.SIM_AI_ENABLE_IMPERFECTIONS = False` for the
  session; new tests must not assume its default.

## What is intentionally not tested

- `telemetry`'s actual MAVLink I/O (serial/UDP) — only the parsing and command
  shaping are unit-tested via fake messages.
- The `sim_ai` background generation loop (a closure inside `run_sim_ai`); its
  pure projection helpers are covered in `test_sim_ai.py`.
- The Hailo camera callback (`ai_callback.py`, a symlink into vendored code).

## Adding a test for a new state

1. Create `tests/test_state_<name>.py`.
2. `sys.path.insert(0, repo_root)`, then import the state module.
3. In each test, build a state with `make_drone_state(...)` and a frame with
   `make_frame(make_detection(...))`.
4. `monkeypatch.setattr(states.<name>, "telemetry_singleton", FakeTelemetry())`
   and likewise for `db_abstraction` / `log_event`.
5. Call the state function and assert on the returned `DroneStateEnum` and on the
   commands recorded by the fakes.

See `tests/test_state_homing.py` for the richest example (timers, velocity law,
altitude bands).
