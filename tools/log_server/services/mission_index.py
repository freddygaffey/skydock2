"""On-disk SQLite index for ``mission.jsonl`` (tools-only; see plan flask_tools_hardening).

Bump ``INDEX_SCHEMA_VERSION`` when the table layout or required JSONL event shapes change.
Readers must reject mismatches and fall back to JSONL parsing (Wave 2+).
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
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

# Rows per executemany during a build. Row-at-a-time INSERT dominated build time on the
# large real logs; batching cuts the sqlite call overhead without a big memory spike.
_INSERT_BATCH = 2000

# Guard against SQLITE_MAX_VARIABLE_NUMBER when expanding an ``event IN (...)`` filter.
_MAX_IN_PARAMS = 400

# --- concurrent-build serialisation ------------------------------------------------------
# The app runs threaded=True and a dashboard load fires half a dozen API requests at once.
# Each one used to call build_mission_index() on the *same* .tmp path: the builders deleted
# each other's tmp file and journal mid-write, and every request failed with
# "disk I/O error" / "attempt to write a readonly database", leaving no index at all
# ("Log index: not built"). One lock per index path, plus a re-check inside it, means the
# first request builds and the rest just wait and reuse the result.
_BUILD_LOCKS: dict[str, threading.Lock] = {}
_BUILD_LOCKS_GUARD = threading.Lock()

# Tmp files left behind by a crashed/killed build, older than this, are safe to sweep.
_STALE_TMP_AGE_S = 6 * 3600


def _build_lock_for(out_path: Path) -> threading.Lock:
    key = str(out_path)
    with _BUILD_LOCKS_GUARD:
        lock = _BUILD_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _BUILD_LOCKS[key] = lock
        return lock


def default_index_path(log_path: Path) -> Path:
    """Sidecar path next to ``mission.jsonl`` (typically under ``missions/NNNN/``)."""
    return log_path.resolve().parent / INDEX_FILENAME


def _connect_rw(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    # Single-file rollback journal: the index is built into a .tmp file and then
    # atomically renamed into place. WAL would leave -wal/-shm sidecars named after
    # the .tmp file; the rename moves only the main db, orphaning the WAL data and
    # leaving an index that can't be reopened (read_meta -> None, never matches).
    # WAL's only benefit is concurrent readers, which a build-once/read-only index
    # doesn't need. TRUNCATE journal avoids per-commit file deletes during the build.
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _cleanup_tmp_sidecars(tmp: Path) -> None:
    """Remove **our own** tmp index and its journal sidecars (tmp, tmp-journal, ...).

    Only files whose name starts with this builder's unique tmp name are touched — globbing
    every ``*.tmp*`` here is what let two concurrent builders destroy each other's work.
    """
    for q in tmp.parent.glob(tmp.name + "*"):  # tmp, tmp-journal, tmp-wal, tmp-shm
        try:
            q.unlink()
        except OSError:
            pass


def _tmp_path_for(out_path: Path) -> Path:
    """Per-builder tmp name, unique across processes and threads."""
    return out_path.with_name(
        f"{out_path.name}.{os.getpid()}.{threading.get_ident():x}.tmp"
    )


def _sweep_stale_tmps(out_path: Path) -> None:
    """Drop tmp files abandoned by a crashed build; never touch a recent (possibly live) one."""
    now = time.time()
    # The old fixed-name tmp ("mission_index.sqlite.tmp") is never used by a current builder,
    # so any copy is dead weight from a crashed pre-fix build — often hundreds of MB.
    legacy = out_path.with_name(out_path.name + ".tmp")
    for q in out_path.parent.glob(legacy.name + "*"):
        try:
            q.unlink()
        except OSError:
            pass
    for q in out_path.parent.glob(out_path.name + ".*.*.tmp*"):
        try:
            if now - q.stat().st_mtime > _STALE_TMP_AGE_S:
                q.unlink()
        except OSError:
            pass


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
    """Build or refresh the sidecar index. Skips work if an up-to-date index exists unless ``force``.

    Serialised per index path: concurrent callers (the parallel API requests a dashboard load
    fires) block here and then find the finished index instead of racing to write the same
    file, which is what produced the intermittent ``disk I/O error`` on big logs.
    """
    log_path = log_path.resolve()
    if not log_path.is_file():
        raise FileNotFoundError(log_path)

    out_path = default_index_path(log_path)
    if out_path.exists() and not force and index_matches_log(log_path, out_path):
        return out_path

    with _build_lock_for(out_path):
        # Another thread may have finished the build while we waited on the lock.
        # `force` still rebuilds unconditionally (that is what the UI's Build button means).
        if not force and out_path.exists() and index_matches_log(log_path, out_path):
            return out_path
        return _build_mission_index_locked(log_path, out_path)


def _build_mission_index_locked(log_path: Path, out_path: Path) -> Path:
    st = log_path.stat()
    _sweep_stale_tmps(out_path)
    tmp = _tmp_path_for(out_path)
    _cleanup_tmp_sidecars(tmp)

    conn = _connect_rw(tmp)
    try:
        _init_schema(conn)
        conn.execute("DELETE FROM meta")
        conn.execute("DELETE FROM events")

        parsed = 0
        batch: list[tuple[str, str]] = []
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
                # Store the original line verbatim: it is already compact JSON and
                # re-serialising it (json.dumps) doubled the build's CPU cost for the
                # big real-mission logs whose rows are ~20 KB each.
                batch.append((ev, line))
                parsed += 1
                if len(batch) >= _INSERT_BATCH:
                    conn.executemany(
                        "INSERT INTO events (event, json) VALUES (?, ?)", batch
                    )
                    batch.clear()
        if batch:
            conn.executemany("INSERT INTO events (event, json) VALUES (?, ?)", batch)
            batch.clear()

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
    except BaseException:
        conn.close()
        # Never leave a half-written tmp behind: the next build would otherwise inherit it.
        _cleanup_tmp_sidecars(tmp)
        raise
    else:
        conn.close()

    tmp.replace(out_path)
    _cleanup_tmp_sidecars(tmp)  # drop any orphaned journal sidecar
    return out_path


def iter_events_from_index(
    index_path: Path,
    *,
    event: str | None = None,
    events: "frozenset[str] | set[str] | tuple[str, ...] | None" = None,
) -> Iterator[dict[str, Any]]:
    """Yield parsed events in log order (same sequence as ``iter_events`` for valid JSON lines).

    ``event`` selects one kind; ``events`` selects several (``WHERE event IN (...)``,
    served by ``idx_events_event``). Both use the index rather than scanning every row,
    which is what makes the "only spray events" style endpoints cheap on 800 MB logs.
    """
    if not index_path.is_file():
        return
    names: tuple[str, ...] | None = None
    post_filter: frozenset[str] | None = None
    if events is not None:
        names = tuple(sorted(set(events)))
        if not names:
            return
        if len(names) > _MAX_IN_PARAMS:
            # Absurdly many kinds (never happens for the real EVENTS registry): scan and
            # filter in Python rather than risk SQLITE_MAX_VARIABLE_NUMBER.
            post_filter = frozenset(names)
            names = None
    conn = sqlite3.connect(f"file:{index_path}?mode=ro", uri=True)
    try:
        if names is not None:
            placeholders = ",".join("?" * len(names))
            cur = conn.execute(
                f"SELECT json FROM events WHERE event IN ({placeholders}) ORDER BY seq",
                names,
            )
        elif event is None:
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
            if not isinstance(obj, dict):
                continue
            if post_filter is not None and obj.get("event") not in post_filter:
                continue
            yield obj
    finally:
        conn.close()


def iter_events_from_index_for_log(
    log_path: Path,
    *,
    event: str | None = None,
    events: "frozenset[str] | set[str] | tuple[str, ...] | None" = None,
    index_path: Path | None = None,
) -> Iterator[dict[str, Any]]:
    """Convenience: read sidecar index for ``log_path`` if present; otherwise yields nothing."""
    p = index_path if index_path is not None else default_index_path(log_path)
    yield from iter_events_from_index(p, event=event, events=events)
