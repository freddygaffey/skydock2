"""On-disk SQLite index for ``mission.jsonl`` (tools-only; see plan flask_tools_hardening).

Bump ``INDEX_SCHEMA_VERSION`` when the table layout or required JSONL event shapes change.
Readers must reject mismatches and fall back to JSONL parsing (Wave 2+).
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterator

# Reserved 1 = implicit / unshipped; start shipped indexes at 2+.
INDEX_SCHEMA_VERSION = 2

INDEX_FILENAME = "mission_index.sqlite"

META_SCHEMA_VERSION = "index_schema_version"
META_LOG_PATH = "log_path_resolved"
META_LOG_MTIME_NS = "log_mtime_ns"
META_LOG_SIZE_BYTES = "log_size_bytes"
META_BUILT_AT_UNIX = "built_at_unix"
META_PARSED_EVENTS = "parsed_event_count"


def default_index_path(log_path: Path) -> Path:
    """Sidecar path next to ``mission.jsonl`` (typically under ``missions/NNNN/``)."""
    return log_path.resolve().parent / INDEX_FILENAME


def _connect_rw(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
            k TEXT PRIMARY KEY NOT NULL,
            v TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS events (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            event TEXT NOT NULL,
            json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_events_event ON events(event);
        """
    )


def read_meta(index_path: Path) -> dict[str, str] | None:
    """Return meta key/value map, or ``None`` if missing/unreadable."""
    if not index_path.is_file():
        return None
    try:
        conn = sqlite3.connect(f"file:{index_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        cur = conn.execute("SELECT k, v FROM meta")
        rows = cur.fetchall()
        if not rows:
            return None
        return {str(k): str(v) for k, v in rows}
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def index_matches_log(log_path: Path, index_path: Path | None = None) -> bool:
    """True if index exists, schema version matches, and ``log_rev`` matches ``log_path`` on disk."""
    p = index_path if index_path is not None else default_index_path(log_path)
    meta = read_meta(p)
    if not meta:
        return False
    try:
        ver = int(meta.get(META_SCHEMA_VERSION, "0"))
    except ValueError:
        return False
    if ver != INDEX_SCHEMA_VERSION:
        return False
    try:
        st = log_path.resolve().stat()
    except OSError:
        return False
    try:
        mtime_ns = int(meta.get(META_LOG_MTIME_NS, "-1"))
        size_b = int(meta.get(META_LOG_SIZE_BYTES, "-1"))
    except ValueError:
        return False
    if mtime_ns != st.st_mtime_ns or size_b != st.st_size:
        return False
    resolved = meta.get(META_LOG_PATH)
    if resolved != str(log_path.resolve()):
        return False
    return True


def build_mission_index(log_path: Path, *, force: bool = False) -> Path:
    """Build or refresh the sidecar index. Skips work if an up-to-date index exists unless ``force``."""
    log_path = log_path.resolve()
    if not log_path.is_file():
        raise FileNotFoundError(log_path)

    out_path = default_index_path(log_path)
    if out_path.exists() and not force and index_matches_log(log_path, out_path):
        return out_path

    st = log_path.stat()
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    if tmp.exists():
        try:
            tmp.unlink()
        except OSError:
            pass

    conn = _connect_rw(tmp)
    try:
        _init_schema(conn)
        conn.execute("DELETE FROM meta")
        conn.execute("DELETE FROM events")

        parsed = 0
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict):
                    continue
                ev = obj.get("event", "")
                if not isinstance(ev, str):
                    ev = str(ev)
                conn.execute(
                    "INSERT INTO events (event, json) VALUES (?, ?)",
                    (ev, json.dumps(obj, separators=(",", ":"), ensure_ascii=False)),
                )
                parsed += 1

        now = str(int(time.time()))
        meta_rows = [
            (META_SCHEMA_VERSION, str(INDEX_SCHEMA_VERSION)),
            (META_LOG_PATH, str(log_path)),
            (META_LOG_MTIME_NS, str(st.st_mtime_ns)),
            (META_LOG_SIZE_BYTES, str(st.st_size)),
            (META_BUILT_AT_UNIX, now),
            (META_PARSED_EVENTS, str(parsed)),
        ]
        conn.executemany("INSERT INTO meta (k, v) VALUES (?, ?)", meta_rows)
        conn.commit()
    finally:
        conn.close()

    tmp.replace(out_path)
    return out_path


def iter_events_from_index(
    index_path: Path,
    *,
    event: str | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield parsed events in log order (same sequence as ``iter_events`` for valid JSON lines)."""
    if not index_path.is_file():
        return
    conn = sqlite3.connect(f"file:{index_path}?mode=ro", uri=True)
    try:
        if event is None:
            cur = conn.execute("SELECT json FROM events ORDER BY seq")
        else:
            cur = conn.execute(
                "SELECT json FROM events WHERE event = ? ORDER BY seq",
                (event,),
            )
        for (raw,) in cur:
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                yield obj
    finally:
        conn.close()


def iter_events_from_index_for_log(
    log_path: Path,
    *,
    event: str | None = None,
    index_path: Path | None = None,
) -> Iterator[dict[str, Any]]:
    """Convenience: read sidecar index for ``log_path`` if present; otherwise yields nothing."""
    p = index_path if index_path is not None else default_index_path(log_path)
    yield from iter_events_from_index(p, event=event)
