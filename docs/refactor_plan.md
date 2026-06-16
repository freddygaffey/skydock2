# skydock2 Refactor Roadmap

Follow-up work beyond the 2026-06 test/docs/fix pass. Each phase is independent
and gated by the test suite (`python -m pytest` green, plus
`tools/log_server/tests/`). The codebase-wide typo rename and the safe bug fixes
are already done — see [code_review_2026-06-13.md](code_review_2026-06-13.md).

Battery/panic failsafe and RTL-resume are **out of scope** — they are handled on
the ArduPilot flight controller by design (see the architecture drift notes).

## Phase 0 — safety net (done)
Pytest suite covering the FSM, every state, the DB layer, mission gen/logging,
and geometry edge cases. This is the precondition for everything below: any
refactor must keep the suite green.

## Phase 1 — dependency injection for singletons
**Problem (review H3):** `db_abstraction` is constructed at import; `telemetry_singleton`
must be assigned before `fsm` is imported. Correct only because `main.py` orders
init carefully.
**Plan:** Define a small `TelemetryLike` Protocol (`fly_to_point`,
`send_velocity_command_yaw_stay_same`, `stop_velocity_command`, `drone_state`).
Pass telemetry and the DB into `StateMachine`, and thread them to state functions
(via a context object or partials) instead of module-level imports. Make
`DBAbstraction` lazily created.
**Payoff:** removes the import-order constraint; lets tests inject fakes without
`monkeypatch.setattr` on each consuming module.
**Risk:** touches every state signature — do it once the suite is the safety net.

## Phase 2 — homing as a state object
**Problem (review H4):** `states/homing.py` keeps `last_det_time` /
`start_homing_time` as module globals; `states/scan.py` keeps a `_scan_data_processed`
latch; `states/shared_data.py` is a module of mutable globals.
**Plan:** Give the FSM per-state `enter()`/`exit()` hooks (the intent of the
deleted commented sketch in `fsm.py`) and move per-state timers/latches into
instances reset on entry.
**Payoff:** no cross-mission state leakage; tests stop needing `reset_state_globals`.

## Phase 3 — constants, config, and magic numbers
**Problem (review H2, M5, M7, L5, L6):** config read from `argv` at import; magic
numbers in homing; duplicate mode maps; truncated `--speed`; unused dep; hardcoded
serial device list.
**Plan:**
- Set `SIM_SPEED` explicitly from `main.py`, not from `argv` in `constants`.
- Name the homing constants currently inlined: horizontal gain `0.7` and cap
  `2 m/s`; climb `-0.4`, search-descend `0.5`, in-band `0.3`, below-floor `-0.3`;
  the spray-altitude tolerance in `MIN_ALT + 1`.
- Single source of truth for the ArduCopter mode map (share `Telemetry.MODE_MAPPING`
  with `drone_state`).
- Accept fractional `--speed`; make the FC serial device configurable.
- Drop `scikit-learn` from `requirements.txt` (clustering is hand-rolled).

## Phase 4 — detection confidence scoring (re-introduce, behind a flag)
**Context:** A multi-factor `score_detection` prototype was removed from
`states/homing.py` (drawio `Homing state` "cal cofidence there"). Homing currently
picks the **nearest** detection. The recorded design combined:
- confidence via a sigmoid around a midpoint (~0.3), with a hard floor (~0.1);
- proximity via exponential decay over a max distance;
- bbox size relative to the image diagonal (fraction ~0.1);
- an aspect-ratio sanity penalty (>2:1 halved).

**Plan:** Re-implement as a pure, unit-tested function returning `(score, dist)`;
select the highest-scoring detection above a `MIN_HOMING_SCORE`. Also gate
spray/scan on a minimum confidence (review note: detections are currently accepted
regardless of confidence). Validate in SITL before enabling on hardware.

## Phase 5 — `spraying()` precision
**Problem (review M4):** marks the closest weed once per in-range detection and
sprays based on any detection's proximity, not the targeted weed's projected
position. **Plan:** spray once per target, keyed to the weed actually being
homed; emit a single `spray_attempt`. Update the pinned test deliberately.

## Phase 6 — tools alignment
- Once enough missions are re-logged with the new key names, simplify the
  old/new-key fallbacks in `tools/log_server/services/projection.py`,
  `analysis.py`, `make_video.py`, `test_camera_orientation.py` (keep one release
  of overlap; old logs are immutable history).
- Add a regression fixture: a small old-format `mission.jsonl` the log_server
  tests replay, so legacy compatibility stays covered.
- Move `tools/test_camera_orientation.py` out of pytest's `test_*` namespace or
  give it a proper test wrapper.

## Notes on the typo rename (completed, for reference)
- DB **columns were already** `rotation_*`; the typos lived on the Python
  dataclass and in `mission.jsonl` keys (derived from `vars()`).
- Per-mission DBs are disposable (fresh `missions/NNNN/droneDB.db` each run), so
  **no DB migration was required**.
- The only compatibility surface was tools that read **old** logs; those now
  accept both spellings (see Phase 6).
- `mission.jsonl` `event` name strings were left unchanged (analysis tools match
  on them).
