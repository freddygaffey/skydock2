# skydock2 Code Review — 2026-06-13

Scope: the flight stack (`main.py`, `fsm.py`, `states/`, `telemetry.py`,
`drone_state.py`, `ai_class.py`, `sim_ai.py`, `utils.py`, `DB*.py`,
`mission_*.py`, `sitl.py`, `constants.py`) reviewed in depth; `tools/` reviewed
lightly; `archive/` and `hailo-rpi5-examples/` (vendored) excluded.

This pass also: applied a codebase-wide typo rename, added a pytest suite
(154 → 273 flight-stack tests), and fixed the safe issues below. Items not fixed
here are cross-referenced to [refactor_plan.md](refactor_plan.md).

## Severity definitions

| Tier | Meaning |
|------|---------|
| Critical | Can crash the flight software or strand the aircraft mid-mission |
| High | Wrong behaviour on a primary mission path, or fragile init |
| Medium | Robustness / correctness on an edge path |
| Low | Hygiene: dead code, stale comments, unused imports |

## Summary

| Status | Count |
|--------|-------|
| Fixed this pass | 10 fixes + full typo rename |
| Deferred → refactor plan | 7 |
| Informational / by-design | 3 |

---

## Critical

### C1 — `rtl()` called `exit()` on the normal mission-complete path — FIXED (F1)
[states/rtl.py](../states/rtl.py). `goto()` returns `RTL` when no unsprayed weeds
remain (still in GUIDED), so the FSM reaches `rtl()`, which called bare `exit()` —
raising `SystemExit` from inside `update()` every successful mission. Replaced with
`return DroneStateEnum.DONE`; the FSM's RTL case already returns `False` to stop
the loop, and `main.py`'s `finally` still runs `kill_sim()`. Locked by
`tests/test_state_rtl.py` and `test_fsm_machine.py`.

### C2 — LAND missing / duplicate AUTOTUNE in telemetry mode map — FIXED (F3)
[telemetry.py](../telemetry.py). The mode dict had a duplicate `'AUTOTUNE'` key
(15 silently lost; 26 mislabeled — it is AUTOROTATE) and **no `'LAND': 8'`**. A
pilot switching to LAND made `move_msg_passer` raise `"mode not found (freddy)"`,
killing the telemetry reader thread. Mapping corrected and promoted to a
`Telemetry.MODE_MAPPING` class attribute (now testable without a serial port).
Locked by `tests/test_safe_fixes.py`.

### C3 — unbound / stale `msg` after `SerialException` — FIXED (F10)
[telemetry.py](../telemetry.py) `start_passer`. `except serial.SerialException: pass`
left `msg` unbound on the first iteration (→ `NameError`, thread dies) or stale on
later ones (the previous message reprocessed). Now sets `msg = None` to fall into
the existing retry path. Locked by `tests/test_safe_fixes.py`.

---

## High

### H1 — `arm_state` not a dataclass field — FIXED (F2)
[drone_state.py](../drone_state.py). `arm_state` was only assigned inside
`set_pass_message`, so any read before the first HEARTBEAT raised `AttributeError`,
and `vars()`-based logging omitted it (so `tools/make_video.py` always defaulted
it). Added `arm_state: bool = False`. Locked by `tests/test_mission_logging.py`.

### H2 — `constants.SIM_SPEED` parsed from `sys.argv` at import — DEFERRED (P3)
[constants.py](../constants.py). Importing `constants` reads `--speed/--speedup`
from `argv`, coupling a config module to CLI invocation and to import timing
(e.g. under tests/tools). Should be set explicitly. → refactor plan Phase 3.

### H3 — import-order-fragile module singletons — DEFERRED (P1)
`db_abstraction = DBAbstraction()` runs at import of
[DB_abstraction.py](../DB_abstraction.py), and `telemetry_singleton` must be set
before `fsm` imports. Correct today only because `main.py` orders things just so.
Dependency injection would remove the hazard. → refactor plan Phase 1.

### H4 — homing keeps mutable module-level state — DEFERRED (P2)
[states/homing.py](../states/homing.py) `last_det_time` / `start_homing_time` are
module globals reset on each exit. Works for a single-threaded FSM but is brittle
and untestable without resetting globals. Move into a state object. → Phase 2.

---

## Medium

### M1 — `load_mission_file` did no schema validation — FIXED (F4)
[sitl.py](../sitl.py). A malformed mission JSON raised a bare `KeyError` deep in
the loader. Now raises a clear `ValueError` naming the missing key / bad
`scan_path` entry. Locked by `tests/test_safe_fixes.py`.

### M2 — SITL heartbeat probe swallowed all exceptions silently — FIXED (F5)
[sitl.py](../sitl.py) `start_sim`. `except Exception: pass` hid every failure of
the "is SITL already running?" probe. Now prints one informative line and
proceeds. Locked by `tests/test_safe_fixes.py`.

### M3 — `mission_dir` mkdir collision window — FIXED (F9)
[mission_logging.py](../mission_logging.py) `allocate_mission_dir`. Hardened the
existence-check/mkdir against a concurrent creator with a bounded retry inside the
existing flock. Locked by the 8-thread `test_mission_logging.py` test.

### M4 — `spraying()` re-marks the same weed per detection — OPEN (informational)
[states/spray.py](../states/spray.py) marks the closest weed sprayed once per
in-range detection and bases the spray on *any* detection's proximity rather than
the targeted weed's. Harmless (idempotent DB update) but imprecise. Behaviour is
pinned by a test so a future fix is a deliberate change.

### M5 — three flight-mode mappings exist — PARTIALLY ADDRESSED
[telemetry.py](../telemetry.py) (now `MODE_MAPPING`) and
[drone_state.py](../drone_state.py) `set_pass_message` keep separate, now-matching
dicts. Consolidating to one source remains. → refactor plan Phase 3.

### M6 — `run_pre_flight_checks` can reference unbound `result` — OPEN
[telemetry.py](../telemetry.py). If `recv_match` times out, `result` may be `None`
or unbound when checked. Low frequency (pre-flight only); flagged for the refactor.

### M7 — `main.py` truncates fractional `--speed` — OPEN
`int(args.speed)` silently floors e.g. `--speed 2.5` to 2. Minor; document or use
float. → refactor plan Phase 3.

---

## Low (mostly fixed this pass)

| ID | Item | Status |
|----|------|--------|
| L1 | Stale "640x640" comments (actual 1280) in `DB.py` | FIXED (F6) |
| L2 | Dead commented blocks: `fsm.py` sketch, `DB.py` legacy sqlite3, `homing.py` score_detection | FIXED (F7) |
| L3 | Unused imports across `states/`, `fsm.py`, `DB*.py`, `utils.py`, `ai_class.py`, `mission_logging.py`, `main.py` | FIXED (F8) |
| L4 | Pervasive identifier typos (`volocity`, `rotaion`, `hight`, `singlton`, `overide`, `prosess`, `connection_palths`, `SCAN_HIGHT`, "lunch atempt") | FIXED (rename) |
| L5 | Unused `scikit-learn` dependency (clustering is hand-rolled) | OPEN → Phase 4 |
| L6 | Hardcoded `/dev/ttyACM*` device list in `telemetry.py` | OPEN → Phase 3 |
| L7 | `heading` can be `None` (MAVLink 65535) | Informational — consumers handle it |

---

## Tools (light review)

- `tools/log_server/services/projection.py` and `analysis.py`, `tools/make_video.py`,
  `tools/test_camera_orientation.py` read drone-state keys from logs. They were
  updated to read the **new** key names (`rotation`, `height`, …) with a
  **fallback to the legacy** (`rotaion`, `hight`) so historical missions still
  replay. The log_server suite passes.
- `tools/test_camera_orientation.py` matches pytest's `test_*` discovery but lives
  under `tools/`; the new `pytest.ini` `testpaths = tests` keeps a bare `pytest`
  run from collecting it.
- `fsm_analyze.py` / `sim_accuracy.py` parse `mission.jsonl` event names; those
  event strings were intentionally left unchanged by the rename.

---

## By-design (not defects)

- **No battery / panic failsafe in Python.** Delegated to the ArduPilot FC, which
  switches to RTL; the FSM observes `mode == "RTL"`. (Drawio `FSM` page drew
  `Panic/Battery → RTL` as in-FSM logic.)
- **No `RTL → OVERRIDE` resume in the FSM.** Mission ends on RTL; re-engagement is
  an FC/pilot action.
- **`heading is None`** is a valid "unknown heading" signal, handled by consumers.
