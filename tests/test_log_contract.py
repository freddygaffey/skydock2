"""
Contract tests for the structured mission log (mission_logging.py, schema v2).

These exist to STOP the logging standard from rotting. Two halves:

1. Encoder / envelope behaviour — feed real project objects (DroneStateForHoming,
   Frame, Detection, DroneStateEnum) through the real log_event and assert the
   on-disk record is clean: enums become their .name (no "DroneStateEnum." leak),
   every record carries the canonical envelope, levels are normalised, the
   drone_state projection has an exact known key set, and the reader surfaces
   malformed lines instead of silently dropping them.

2. Producer source scan — parse every module that emits events and FAIL if it
   uses an event name that isn't registered in EVENTS, stringifies a state enum
   at the call site (the original bug), or uses a non-canonical level spelling.

Run with:  python -m pytest tests/test_log_contract.py
       or:  python tests/test_log_contract.py
"""

import ast
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Load the REAL mission_logging by file path. Other tests (test_sim_ai) install a
# MagicMock stub under the name "mission_logging" in sys.modules; importing by path
# under a private name guarantees we exercise the real encoders regardless of order.
_spec = importlib.util.spec_from_file_location(
    "mission_logging_under_test", ROOT / "mission_logging.py"
)
ml = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ml)

from ai_class import Detection, Frame  # noqa: E402
from drone_state import DroneStateForHoming, Rotation, GPSFix  # noqa: E402
from states.enum import DroneStateEnum  # noqa: E402

# Files that emit events. Keep this list in step with the codebase; the source
# scan only protects what it reads.
PRODUCER_FILES = [
    ROOT / "main.py",
    ROOT / "fsm.py",
    ROOT / "telemetry.py",
    ROOT / "sim_ai.py",
    ROOT / "DB_abstraction.py",
    *sorted((ROOT / "states").glob("*.py")),
]

# Functions whose first positional arg is the event name.
_EMIT_FUNCS = {"log_event", "_db_mission_log"}
# Call-site kwargs that must carry a raw enum, never str(enum).
_STATE_KWARGS = {"state", "state_from", "state_to"}

# The frozen shape of the encoded drone_state. Changing the encoder must update
# this set deliberately — that's the point.
EXPECTED_DRONE_STATE_KEYS = {
    "latitude", "longitude", "altitude_rel_home",
    "velocity_x", "velocity_y", "velocity_z",
    "heading", "mode", "arm_state", "autonomy_enabled", "force_homing",
    "rangefinder_m", "width", "height",
    "rotation", "rotation_history", "gps_history",
}


def _read_records(path: Path) -> list[dict]:
    return list(ml.iter_events(path))


def _emit_one(event: str, **kw) -> dict:
    """Configure a throwaway mission dir, emit one event, return the parsed record."""
    with tempfile.TemporaryDirectory() as d:
        ml.configure_mission_dir(Path(d))
        ml.init_mission_log(is_sim=True)
        ml.log_event(event, **kw)
        recs = _read_records(Path(d) / "mission.jsonl")
    # recs[0] is the mission_start header; recs[-1] is our event.
    return recs[-1]


def _iter_emit_calls():
    """Yield (file, ast.Call) for every log_event / _db_mission_log call site."""
    for f in PRODUCER_FILES:
        if not f.exists():
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
            if name in _EMIT_FUNCS:
                yield f, node


class TestEncoderContract(unittest.TestCase):
    def test_enum_encodes_to_name(self):
        self.assertEqual(ml._encode(DroneStateEnum.SCAN), "SCAN")
        self.assertEqual(ml._encode(DroneStateEnum.HOMING), "HOMING")

    def test_no_enum_repr_leaks_to_disk(self):
        with tempfile.TemporaryDirectory() as d:
            ml.configure_mission_dir(Path(d))
            ml.init_mission_log()
            ml.log_event(
                "fsm_transition", logger="fsm",
                state_from=DroneStateEnum.GOTO, state_to=DroneStateEnum.SCAN,
            )
            raw = (Path(d) / "mission.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("DroneStateEnum.", raw)
        rec = json.loads(raw.strip().splitlines()[-1])
        self.assertEqual(rec["state_from"], "GOTO")
        self.assertEqual(rec["state_to"], "SCAN")

    def test_envelope_always_present(self):
        rec = _emit_one("fsm_tick", logger="fsm", level="DEBUG",
                        state=DroneStateEnum.SCAN)
        for key in ("time_ns", "ts", "level", "logger", "event"):
            self.assertIn(key, rec)
        self.assertIsInstance(rec["time_ns"], int)
        self.assertTrue(rec["ts"].endswith("Z"))
        self.assertEqual(rec["event"], "fsm_tick")
        self.assertEqual(rec["logger"], "fsm")

    def test_level_normalised(self):
        self.assertEqual(_emit_one("homing_alt_cap", logger="homing",
                                   level="WARN")["level"], "WARNING")
        self.assertEqual(_emit_one("fsm_tick", logger="fsm",
                                   level="info")["level"], "INFO")
        self.assertEqual(_emit_one("fsm_tick", logger="fsm",
                                   level="bogus")["level"], "INFO")

    def test_drone_state_projection_is_exact_and_clean(self):
        ds = DroneStateForHoming()
        rec = _emit_one("telemetry_sample", logger="telemetry", drone_state=ds)
        encoded = rec["drone_state"]
        self.assertEqual(set(encoded.keys()), EXPECTED_DRONE_STATE_KEYS)
        # Typo corrected on disk; internal name must not leak.
        self.assertIn("rotation", encoded)
        self.assertNotIn("rotaion", encoded)
        self.assertIsInstance(encoded["rotation"], dict)
        self.assertEqual(
            set(encoded["rotation"].keys()), {"time_ns", "x", "y", "z", "dx", "dy", "dz"}
        )

    def test_history_buffers_collapse_to_newest_used_sample(self):
        # The rolling rotation/gps buffers (maxlen 100) must NOT be dumped in full on every
        # record — that O(n) per-line blowup produced 14 GB mission logs. Only the newest
        # sample (the value actually used for this record's projection) is logged.
        ds = DroneStateForHoming()
        for i in range(100):
            ds.rotation_history.append(Rotation(time_ns=i, x=float(i), y=0.0, z=0.0))
            ds.gps_history.append(GPSFix(time_ns=i, lat=float(i), lon=0.0, vx=0.0, vy=0.0))
        rec = _emit_one("telemetry_sample", logger="telemetry", drone_state=ds)
        encoded = rec["drone_state"]
        # Keys unchanged (schema stable), but each history is now exactly the last entry.
        self.assertEqual(set(encoded.keys()), EXPECTED_DRONE_STATE_KEYS)
        self.assertEqual(len(encoded["rotation_history"]), 1)
        self.assertEqual(len(encoded["gps_history"]), 1)
        self.assertEqual(encoded["rotation_history"][0]["x"], 99.0)
        self.assertEqual(encoded["rotation_history"][0]["time_ns"], 99)
        self.assertEqual(encoded["gps_history"][0]["lat"], 99.0)

    def test_empty_history_encodes_as_empty_list(self):
        ds = DroneStateForHoming()  # fresh buffers are empty
        encoded = _emit_one("telemetry_sample", logger="telemetry",
                            drone_state=ds)["drone_state"]
        self.assertEqual(encoded["rotation_history"], [])
        self.assertEqual(encoded["gps_history"], [])

    def test_detection_uses_time_detected_not_time_ns(self):
        det = Detection(label="sports ball", confidence=0.9,
                        bbox=[(1, 2), (3, 4)], time_ns=123)
        frame = Frame([det], drone_state=DroneStateForHoming())
        rec = _emit_one("weed_detected", logger="ai", frame=frame)
        d0 = rec["frame"]["detections"][0]
        self.assertIn("time_detected", d0)
        self.assertNotIn("time_ns", d0)
        self.assertEqual(d0["time_detected"], 123)
        self.assertEqual(d0["label"], "sports ball")

    def test_unregistered_event_warns_but_still_logs(self):
        buf = io.StringIO()
        with tempfile.TemporaryDirectory() as d:
            ml.configure_mission_dir(Path(d))
            ml.init_mission_log()
            ml._warned_unknown_events.discard("totally_made_up_event")
            with redirect_stderr(buf):
                ml.log_event("totally_made_up_event", logger="x")
            recs = _read_records(Path(d) / "mission.jsonl")
        self.assertIn("totally_made_up_event", buf.getvalue())
        self.assertEqual(recs[-1]["event"], "totally_made_up_event")

    def test_iter_events_surfaces_malformed_lines(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "mission.jsonl"
            p.write_text('{"event":"ok"}\nthis is not json\n{"event":"ok2"}\n',
                         encoding="utf-8")
            buf = io.StringIO()
            with redirect_stderr(buf):
                recs = list(ml.iter_events(p))
            self.assertEqual([r["event"] for r in recs], ["ok", "ok2"])
            self.assertIn("malformed", buf.getvalue())
            # strict mode refuses to paper over corruption
            with self.assertRaises(json.JSONDecodeError):
                list(ml.iter_events(p, strict=True))


class TestProducerSourceContract(unittest.TestCase):
    def test_every_emitted_event_is_registered(self):
        offenders = []
        for f, call in _iter_emit_calls():
            if call.args and isinstance(call.args[0], ast.Constant) \
                    and isinstance(call.args[0].value, str):
                name = call.args[0].value
                if name not in ml.EVENTS:
                    offenders.append((f.name, call.lineno, name))
        self.assertEqual(
            offenders, [],
            "Unregistered event names emitted (add them to EVENTS in "
            f"mission_logging.py): {offenders}",
        )

    def test_no_state_kwarg_is_stringified(self):
        # Forbids the original bug: log_event(..., state_to=str(enum)) which leaked
        # "DroneStateEnum.SCAN" onto disk. Pass the raw enum instead.
        offenders = []
        for f, call in _iter_emit_calls():
            for kw in call.keywords:
                if kw.arg in _STATE_KWARGS and isinstance(kw.value, ast.Call):
                    vfn = kw.value.func
                    if getattr(vfn, "id", None) == "str":
                        offenders.append((f.name, call.lineno, kw.arg))
        self.assertEqual(
            offenders, [],
            f"State kwargs must pass the raw enum, not str(enum): {offenders}",
        )

    def test_levels_are_canonical_at_source(self):
        offenders = []
        for f, call in _iter_emit_calls():
            for kw in call.keywords:
                if kw.arg == "level" and isinstance(kw.value, ast.Constant) \
                        and isinstance(kw.value.value, str):
                    if kw.value.value not in ml._VALID_LEVELS:
                        offenders.append((f.name, call.lineno, kw.value.value))
        self.assertEqual(
            offenders, [],
            "Non-canonical level spellings (use DEBUG/INFO/WARNING/ERROR/CRITICAL): "
            f"{offenders}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
