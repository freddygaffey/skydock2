"""Tests for mission_logging.py — mission-dir allocation and JSONL event logging.

All file I/O is confined to tmp_path; the real missions/ directory is never
touched. The module keeps global state (_mission_dir etc.), so each test
reconfigures it explicitly.

Run with:  python -m pytest tests/test_mission_logging.py
"""

import json
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.support import ensure_real_module  # noqa: E402

ml = ensure_real_module("mission_logging")

from drone_state import DroneStateForHoming, Rotation  # noqa: E402
from ai_class import Detection, Frame  # noqa: E402


@pytest.fixture
def configured(tmp_path):
    """Configure mission_logging to write into a fresh tmp mission dir."""
    mission_dir = tmp_path / "0001"
    mission_dir.mkdir()
    ml.configure_mission_dir(mission_dir)
    yield mission_dir
    # Reset module globals so other tests start clean.
    ml.configure_mission_dir(tmp_path / "_unused")


def read_lines(path):
    return [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]


# ---------------------------------------------------------------------------
# allocate_mission_dir
# ---------------------------------------------------------------------------

def test_allocate_starts_at_one(tmp_path):
    d = ml.allocate_mission_dir(tmp_path)
    assert d.name == "0001"
    assert d.is_dir()


def test_allocate_increments(tmp_path):
    first = ml.allocate_mission_dir(tmp_path)
    second = ml.allocate_mission_dir(tmp_path)
    assert first.name == "0001"
    assert second.name == "0002"


def test_allocate_skips_existing_dirs_without_counter(tmp_path):
    (tmp_path / "missions").mkdir()
    (tmp_path / "missions" / "0007").mkdir()
    d = ml.allocate_mission_dir(tmp_path)
    assert d.name == "0008"


def test_allocate_ignores_non_digit_dirs(tmp_path):
    (tmp_path / "missions").mkdir()
    (tmp_path / "missions" / "scratch").mkdir()
    d = ml.allocate_mission_dir(tmp_path)
    assert d.name == "0001"


def test_allocate_concurrent_unique(tmp_path):
    results = []
    lock = threading.Lock()

    def worker():
        d = ml.allocate_mission_dir(tmp_path)
        with lock:
            results.append(d.name)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 8
    assert len(set(results)) == 8  # no collisions under the flock


# ---------------------------------------------------------------------------
# init_mission_log
# ---------------------------------------------------------------------------

def test_init_writes_header_once(configured):
    path = ml.init_mission_log(is_sim=True, truth_file="cmac3.json")
    ml.init_mission_log(is_sim=True)  # idempotent — size > 0 short-circuits

    lines = read_lines(path)
    assert len(lines) == 1
    assert lines[0]["event"] == "mission_start"
    assert lines[0]["is_sim"] is True
    assert lines[0]["sim_truth_file"] == "cmac3.json"


def test_init_requires_configured_dir(tmp_path):
    ml.configure_mission_dir(tmp_path / "_unused")
    # _mission_log_path is set, but simulate the unconfigured case directly.
    ml._mission_dir = None
    ml._mission_log_path = None
    with pytest.raises(RuntimeError):
        ml.init_mission_log()


# ---------------------------------------------------------------------------
# log_event
# ---------------------------------------------------------------------------

def test_log_event_noop_when_unconfigured(tmp_path):
    ml._mission_dir = None
    ml._mission_log_path = None
    # Should silently no-op, not raise.
    ml.log_event("x", logger="test")


def test_log_event_writes_valid_jsonl(configured):
    ml.init_mission_log()
    ml.log_event("custom", logger="test", level="INFO", value=42, ignored=None)

    lines = read_lines(ml.get_mission_log_path())
    record = lines[-1]
    assert record["event"] == "custom"
    assert record["value"] == 42
    assert "ignored" not in record  # None fields are dropped


def test_serialize_drone_state_uses_rotation_key_and_includes_arm_state(configured):
    ml.init_mission_log()
    state = DroneStateForHoming()
    state.latitude = -35.3
    state.longitude = 149.1
    state.rotation = Rotation(time_ns=0, x=0.1, y=0.2, z=0.3)

    ml.log_event("snap", logger="test", drone_state=state)

    record = read_lines(ml.get_mission_log_path())[-1]
    ds = record["drone_state"]
    assert ds["latitude"] == pytest.approx(-35.3)
    # Correctly-spelled rotation key after the rename.
    assert "rotation" in ds
    assert "rotaion" not in ds
    # F2: arm_state is a dataclass field, so it appears in the vars()-based dump.
    assert ds["arm_state"] is False


def test_serialize_frame_detections(configured):
    ml.init_mission_log()
    det = Detection(label="sports ball", confidence=0.9,
                    bbox=[(1.0, 2.0), (3.0, 4.0)], track_id=5, truth_id=2, time_ns=999)
    ml.log_event("snap", logger="test", frame=Frame([det], photo_path="p.jpg", drone_state=DroneStateForHoming()))

    record = read_lines(ml.get_mission_log_path())[-1]
    fr = record["frame"]
    assert fr["photo_path"] == "p.jpg"
    assert fr["detections"][0]["label"] == "sports ball"
    assert fr["detections"][0]["time_detected"] == 999
    assert fr["detections"][0]["truth_id"] == 2


def test_jsonable_handles_paths_and_objects(configured):
    ml.init_mission_log()
    ml.log_event("e", logger="t", a_path=Path("/tmp/x"), nested={"k": [1, 2]})
    record = read_lines(ml.get_mission_log_path())[-1]
    assert record["a_path"] == "/tmp/x"
    assert record["nested"] == {"k": [1, 2]}
