"""Mission listings are ordered by flight start time, newest first.

The mission id is not a reliable clock (RPi logs are pulled out of order, sim runs reuse
numbering), so the order comes from each log's ``mission_start`` header. Reading it must stay
cheap: only the first line of ``mission.jsonl`` is parsed, never the whole file.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from factory import create_app
from services.mission_store import mission_paths, mission_start_ts


def _write_mission(root: Path, mid: str, header: dict | None, extra_lines: int = 0) -> Path:
    d = root / mid
    d.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if header is not None:
        lines.append(json.dumps(header))
    for i in range(extra_lines):
        lines.append(json.dumps({"event": "telemetry_sample", "ts": "2030-01-01T00:00:00.000Z",
                                 "n": i}))
    (d / "mission.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return d


def _header(ts: str, time_ns: int | None = None) -> dict:
    h = {"event": "mission_start", "level": "INFO", "logger": "main", "ts": ts,
         "schema_version": 2}
    if time_ns is not None:
        h["time_ns"] = time_ns
    return h


@pytest.fixture()
def roots():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


def test_mission_paths_newest_flight_first(roots: Path):
    # Deliberately: the *lower* mission id is the *newer* flight.
    _write_mission(roots, "0002", _header("2026-05-01T10:00:00.000Z"))
    _write_mission(roots, "0007", _header("2026-01-02T09:00:00.000Z"))
    _write_mission(roots, "0004", _header("2026-03-03T09:00:00.000Z"))
    assert [p.name for p in mission_paths(roots)] == ["0002", "0004", "0007"]


def test_time_ns_header_wins_over_ts(roots: Path):
    _write_mission(roots, "0001", _header("2020-01-01T00:00:00.000Z", time_ns=2_000_000_000_000_000_000))
    _write_mission(roots, "0002", _header("2030-01-01T00:00:00.000Z", time_ns=1_000_000_000_000_000_000))
    assert [p.name for p in mission_paths(roots)] == ["0001", "0002"]


def test_missing_or_malformed_header_falls_back_to_mtime(roots: Path):
    import os

    a = _write_mission(roots, "0001", None)          # no header line at all
    b = _write_mission(roots, "0002", {"event": "telemetry_sample", "ts": "x"})  # wrong event
    (roots / "0003").mkdir()
    (roots / "0003" / "mission.jsonl").write_text("{not json\n", encoding="utf-8")
    # 0003 newest, then 0001, then 0002.
    os.utime(b / "mission.jsonl", (1_000_000, 1_000_000))
    os.utime(a / "mission.jsonl", (2_000_000, 2_000_000))
    os.utime(roots / "0003" / "mission.jsonl", (3_000_000, 3_000_000))
    assert [p.name for p in mission_paths(roots)] == ["0003", "0001", "0002"]


def test_mission_start_ts_reads_only_the_first_line(roots: Path, monkeypatch):
    """A multi-MB tail must not be read just to order the listing.

    Asserts the perf property directly (bytes pulled off disk), not merely the result —
    a listing that parses 60 real mission logs would take minutes.
    """
    import builtins

    d = _write_mission(roots, "0001", _header("2026-05-01T10:00:00.000Z"), extra_lines=20000)
    log = d / "mission.jsonl"
    size = log.stat().st_size
    assert size > 1_000_000

    real_open = builtins.open
    read_bytes = []

    class _CountingFile:
        def __init__(self, f):
            self._f = f

        def readline(self, *a, **k):
            out = self._f.readline(*a, **k)
            read_bytes.append(len(out))
            return out

        def __getattr__(self, name):
            return getattr(self._f, name)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return self._f.__exit__(*exc)

    def fake_open(file, *a, **k):
        f = real_open(file, *a, **k)
        return _CountingFile(f) if str(file) == str(log) else f

    monkeypatch.setattr(builtins, "open", fake_open)
    ts = mission_start_ts(log)

    assert ts == pytest.approx(1777629600.0, abs=86400)  # 2026-05-01, tz-independent
    assert sum(read_bytes) < 4096, f"read {sum(read_bytes)} bytes of a {size}-byte log"


def test_listing_page_and_dashboard_nav_are_newest_first(roots: Path):
    _write_mission(roots, "0005", _header("2026-01-01T00:00:00.000Z"))
    _write_mission(roots, "0006", _header("2026-06-01T00:00:00.000Z"))
    app = create_app()
    app.config.update(MISSIONS_ROOT=roots, RPI_MISSIONS_ROOT=roots, SIM_DATA_ROOT=roots,
                      TESTING=True)
    c = app.test_client()

    for src in ("sim", "rpi"):
        html = c.get(f"/missions?src={src}").get_data(as_text=True)
        assert html.index("0006") < html.index("0005"), f"src={src} not newest-first"

    # The per-mission nav list (used for prev/next) follows the same order.
    page = c.get("/missions/0006?src=rpi").get_data(as_text=True)
    assert '["0006", "0005"]' in page or '["0006","0005"]' in page


def test_latest_shortcut_resolves_to_newest_flight(roots: Path):
    _write_mission(roots, "0005", _header("2026-01-01T00:00:00.000Z"))
    _write_mission(roots, "0006", _header("2026-06-01T00:00:00.000Z"))
    app = create_app()
    app.config.update(MISSIONS_ROOT=roots, RPI_MISSIONS_ROOT=roots, SIM_DATA_ROOT=roots,
                      TESTING=True)
    c = app.test_client()
    page = c.get("/gc?src=sim").get_data(as_text=True)
    assert "Mission 0006" in page
