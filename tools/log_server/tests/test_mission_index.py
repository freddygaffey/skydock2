from __future__ import annotations

from pathlib import Path

from services.mission_index import (
    INDEX_SCHEMA_VERSION,
    build_mission_index,
    default_index_path,
    index_matches_log,
    iter_events_from_index,
)
from services.mission_store import _iter_events_from_file, iter_events


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
