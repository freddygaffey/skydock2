from __future__ import annotations

from pathlib import Path

from services.analysis import build_summary_payload


def _fixture_log() -> Path:
    return Path(__file__).resolve().parent / "fixtures" / "minimal_mission.jsonl"


def test_build_summary_payload_fixture() -> None:
    p = _fixture_log()
    s = build_summary_payload(p)
    assert s["duration_s"] >= 0
    assert "event_counts" in s
    assert s["event_counts"].get("fsm_tick", 0) >= 1
    assert s["insights"]["jsonl_lines"] >= 1
