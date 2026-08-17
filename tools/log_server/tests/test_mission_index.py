from __future__ import annotations

import json
import threading
from pathlib import Path

from services.mission_index import (
    INDEX_SCHEMA_VERSION,
    build_mission_index,
    default_index_path,
    index_matches_log,
    iter_events_from_index,
)
from services.mission_store import (
    _iter_events_from_file,
    iter_events,
    iter_events_of_kinds,
)


def _fixture_log() -> Path:
    return Path(__file__).resolve().parent / "fixtures" / "minimal_mission.jsonl"


def test_build_index_creates_sidecar(tmp_path: Path) -> None:
    src = _fixture_log()
    dst = tmp_path / "mission.jsonl"
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    out = build_mission_index(dst, force=True)
    assert out == default_index_path(dst)
    assert out.is_file()
    assert index_matches_log(dst, out)


def test_iter_events_matches_file_when_indexed(tmp_path: Path) -> None:
    src = _fixture_log()
    dst = tmp_path / "mission.jsonl"
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    build_mission_index(dst, force=True)
    from_file = list(_iter_events_from_file(dst))
    indexed = list(iter_events(dst))
    assert len(from_file) == len(indexed)
    for a, b in zip(from_file, indexed):
        assert a == b


def test_schema_version_in_meta(tmp_path: Path) -> None:
    dst = tmp_path / "mission.jsonl"
    dst.write_text(_fixture_log().read_text(encoding="utf-8"), encoding="utf-8")
    ip = build_mission_index(dst, force=True)
    import sqlite3

    conn = sqlite3.connect(str(ip))
    try:
        r = conn.execute("SELECT v FROM meta WHERE k = ?", ("index_schema_version",)).fetchone()
        assert r is not None
        assert int(r[0]) == INDEX_SCHEMA_VERSION
    finally:
        conn.close()


def test_index_iterator_filtered_fsm_tick(tmp_path: Path) -> None:
    dst = tmp_path / "mission.jsonl"
    dst.write_text(_fixture_log().read_text(encoding="utf-8"), encoding="utf-8")
    ip = build_mission_index(dst, force=True)
    ticks = list(iter_events_from_index(ip, event="fsm_tick"))
    assert len(ticks) == 1
    assert ticks[0].get("event") == "fsm_tick"


# --- multi-kind index queries -------------------------------------------------------------

def test_index_iterator_multi_kind_in_log_order(tmp_path: Path) -> None:
    dst = tmp_path / "mission.jsonl"
    dst.write_text(_fixture_log().read_text(encoding="utf-8"), encoding="utf-8")
    ip = build_mission_index(dst, force=True)
    kinds = {"fsm_transition", "weed_detected"}
    rows = list(iter_events_from_index(ip, events=kinds))
    assert [r["event"] for r in rows] == ["fsm_transition", "weed_detected"]  # log order
    assert list(iter_events_from_index(ip, events=set())) == []


def test_iter_events_of_kinds_matches_with_and_without_index(tmp_path: Path) -> None:
    """The sqlite path and the JSONL fallback must return the same rows, in the same order."""
    dst = tmp_path / "mission.jsonl"
    dst.write_text(_fixture_log().read_text(encoding="utf-8"), encoding="utf-8")
    kinds = {"fsm_transition", "weed_detected", "telemetry_sample"}

    # No index yet -> JSONL fallback (auto-build disabled by pointing at a read-only-ish name
    # is fiddly, so compare against an explicit unindexed read of the same file instead).
    expected = [e for e in _iter_events_from_file(dst) if e.get("event") in kinds]

    build_mission_index(dst, force=True)
    assert list(iter_events_of_kinds(dst, kinds)) == expected


def test_iter_events_of_kinds_ignores_substring_lookalikes(tmp_path: Path) -> None:
    """The JSONL fallback prescreens on a substring; it must still match on the real field."""
    dst = tmp_path / "mission.jsonl"
    dst.write_text(
        "\n".join(
            json.dumps(x)
            for x in (
                {"event": "fsm_transition", "state_to": "SCAN"},
                # 'fsm_transition' appears as a *value*, not as this row's event.
                {"event": "move_command", "note": '"event":"fsm_transition" lookalike'},
            )
        )
        + "\n",
        encoding="utf-8",
    )
    rows = list(iter_events_of_kinds(dst, {"fsm_transition"}))
    assert [r["event"] for r in rows] == ["fsm_transition"]


# --- concurrency ---------------------------------------------------------------------------

def test_concurrent_builds_do_not_corrupt_index(tmp_path: Path) -> None:
    """Regression: parallel dashboard requests each started a build into the SAME tmp file,
    deleted each other's journal, and every one failed with sqlite "disk I/O error" —
    leaving the mission permanently showing "Log index: not built"."""
    dst = tmp_path / "mission.jsonl"
    body = _fixture_log().read_text(encoding="utf-8")
    dst.write_text(body * 200, encoding="utf-8")  # big enough that builds actually overlap

    errors: list[str] = []
    barrier = threading.Barrier(8)

    def run() -> None:
        barrier.wait()
        try:
            build_mission_index(dst, force=False)
        except Exception as exc:  # noqa: BLE001 - the whole point is to catch any failure
            errors.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=run) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    ip = default_index_path(dst)
    assert index_matches_log(dst, ip)
    # No half-written tmp/journal files left next to the index.
    leftovers = [p.name for p in tmp_path.glob("mission_index.sqlite.*")]
    assert leftovers == [], leftovers


def test_force_rebuild_still_rebuilds_when_index_is_current(tmp_path: Path) -> None:
    """The UI's Build button (force=True) must not be short-circuited by the build lock."""
    dst = tmp_path / "mission.jsonl"
    dst.write_text(_fixture_log().read_text(encoding="utf-8"), encoding="utf-8")
    ip = build_mission_index(dst, force=True)
    import sqlite3

    conn = sqlite3.connect(str(ip))
    try:
        conn.execute("DELETE FROM events")
        conn.commit()
    finally:
        conn.close()
    assert list(iter_events_from_index(ip)) == []

    build_mission_index(dst, force=True)
    assert len(list(iter_events_from_index(ip))) == 5
