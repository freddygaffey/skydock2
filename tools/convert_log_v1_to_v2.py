#!/usr/bin/env python3
"""
Convert legacy (schema v1) mission.jsonl logs to the schema v2 format produced by
mission_logging.py.

The logging overhaul (June 13 2026) made a clean break: the v2 reader
(mission_logging.iter_events) does NOT normalize v1 records. This one-shot tool
migrates old logs so the v2 tools (sim_accuracy.py, fsm_analyze.py, log_server, ...)
can read them.

What it rewrites
----------------
Envelope:
  - injects ``time_ns`` when missing (derived from the millisecond ``ts``; not exact,
    but monotonic enough for ordering — real v1 nanos were never recorded)
  - normalizes the ``level`` spelling (v1 "WARN" -> "WARNING")
  - bumps ``schema_version`` to 2 on the mission_start header

drone_state (the bulk of the churn):
  - ``rotaion``                  -> ``rotation``         (typo fix)
  - ``rotaion_history``          -> ``rotation_history`` (and parsed if it was a
                                    Python repr string like "deque([Rotation(...)])")
  - ``gps_history``              -> parsed the same way if it was a repr string
  - ``hight``                    -> ``height``
  - ``enable_homing_and_autonomy`` -> ``autonomy_enabled``
  - drops ``time_updated_GLOBAL_POSITION_INT`` / ``time_updated_angle`` (gone in v2)
  - emits exactly the v2 key set; absent fields become null

Lines that are not valid JSON (some v1 telemetry rows were written truncated, leaving
an unterminated string) cannot be salvaged — they are dropped and counted, never
silently swallowed.

Usage
-----
    # convert one file -> writes mission.v2.jsonl next to it
    python tools/convert_log_v1_to_v2.py missions/0030/mission.jsonl

    # convert every mission.jsonl under a tree
    python tools/convert_log_v1_to_v2.py logs/

    # rewrite in place (original backed up to mission.v1.jsonl)
    python tools/convert_log_v1_to_v2.py --in-place logs/

    # custom output path (single input only)
    python tools/convert_log_v1_to_v2.py missions/0030/mission.jsonl -o /tmp/out.jsonl
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 2

_LEVEL_ALIASES = {"WARN": "WARNING", "ERR": "ERROR", "FATAL": "CRITICAL"}
_VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

# v1 drone_state field name -> v2 name (fields not listed are passed through as-is if
# they're part of the v2 key set, otherwise dropped).
_DS_RENAME = {
    "rotaion": "rotation",
    "rotaion_history": "rotation_history",
    "hight": "height",
    "enable_homing_and_autonomy": "autonomy_enabled",
}
# v2 drone_state keys, in mission_logging._encode_drone_state order.
_DS_V2_KEYS = [
    "latitude", "longitude", "altitude_rel_home",
    "velocity_x", "velocity_y", "velocity_z",
    "heading", "mode", "arm_state", "autonomy_enabled", "force_homing",
    "rangefinder_m", "width", "height",
    "rotation", "rotation_history", "gps_history",
]
_DS_DROP = {"time_updated_GLOBAL_POSITION_INT", "time_updated_angle"}

_ROTATION_KEYS = ["time_ns", "x", "y", "z", "dx", "dy", "dz"]
_GPSFIX_KEYS = ["time_ns", "lat", "lon", "vx", "vy"]

# Matches "Key=Value" pairs inside a Rotation(...)/GPSFix(...) repr.
_KV_RE = re.compile(r"(\w+)=([-+0-9.eE]+|None)")
# Matches each "Name(...)" record inside a "deque([...])" repr.
_RECORD_RE = re.compile(r"(\w+)\(([^)]*)\)")


def _norm_level(level):
    s = str(level or "INFO").upper()
    s = _LEVEL_ALIASES.get(s, s)
    return s if s in _VALID_LEVELS else "INFO"


def _ts_to_ns(ts):
    """Derive a time_ns from an ISO ``ts`` string. Millisecond resolution only."""
    if not ts:
        return None
    try:
        s = str(ts).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1_000_000_000)
    except Exception:
        return None


def _coerce_num(tok):
    if tok == "None":
        return None
    try:
        if any(c in tok for c in ".eE"):
            return float(tok)
        return int(tok)
    except ValueError:
        return None


def _parse_repr_records(s, keys):
    """Parse a Python repr like "deque([Rotation(a=1, b=2), Rotation(...)])" into a
    list of dicts keyed by ``keys``. Returns [] on anything unrecognised."""
    out = []
    for _name, body in _RECORD_RE.findall(s):
        kv = {k: _coerce_num(v) for k, v in _KV_RE.findall(body)}
        out.append({k: kv.get(k) for k in keys})
    return out


def _as_record_list(value, keys):
    """Normalize a v1 history field (either already a list of dicts, or a repr string)
    into a list of dicts with the canonical ``keys``."""
    if value is None:
        return []
    if isinstance(value, str):
        return _parse_repr_records(value, keys)
    if isinstance(value, list):
        out = []
        for item in value:
            if isinstance(item, dict):
                out.append({k: item.get(k) for k in keys})
            elif isinstance(item, str):
                out.extend(_parse_repr_records(item, keys))
        return out
    return []


def _normalize_rotation(value):
    if value is None:
        return None
    if isinstance(value, str):
        recs = _parse_repr_records(value, _ROTATION_KEYS)
        return recs[0] if recs else None
    if isinstance(value, dict):
        return {k: value.get(k) for k in _ROTATION_KEYS}
    return None


def convert_drone_state(ds):
    if ds is None:
        return None
    # Apply renames into a working copy first.
    src = {}
    for k, v in ds.items():
        if k in _DS_DROP:
            continue
        src[_DS_RENAME.get(k, k)] = v

    out = {}
    for k in _DS_V2_KEYS:
        out[k] = src.get(k)
    out["rotation"] = _normalize_rotation(src.get("rotation"))
    out["rotation_history"] = _as_record_list(src.get("rotation_history"), _ROTATION_KEYS)
    out["gps_history"] = _as_record_list(src.get("gps_history"), _GPSFIX_KEYS)
    return out


def convert_record(rec):
    """Transform one already-parsed v1 record dict into a v2 record dict."""
    out = dict(rec)

    out["level"] = _norm_level(rec.get("level"))

    if "time_ns" not in out or out.get("time_ns") is None:
        ns = _ts_to_ns(rec.get("ts"))
        if ns is not None:
            out["time_ns"] = ns

    if rec.get("event") == "mission_start":
        out["schema_version"] = SCHEMA_VERSION

    if "drone_state" in out:
        out["drone_state"] = convert_drone_state(out["drone_state"])

    # Reorder so the canonical envelope leads each line (cosmetic; matches v2 writer).
    envelope = ("time_ns", "ts", "level", "logger", "event")
    ordered = {k: out[k] for k in envelope if k in out}
    for k, v in out.items():
        if k not in ordered:
            ordered[k] = v
    return ordered


def convert_file(in_path, out_path):
    """Convert one file. Returns (converted, skipped_already_v2, dropped_bad_lines)."""
    converted = dropped = 0
    already_v2 = False
    lines_out = []
    with open(in_path, "r", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError as e:
                dropped += 1
                print(f"  drop {in_path}:{lineno}: malformed JSON ({e})", file=sys.stderr)
                continue
            if rec.get("event") == "mission_start" and rec.get("schema_version") == SCHEMA_VERSION:
                already_v2 = True
            v2 = convert_record(rec)
            lines_out.append(json.dumps(v2, separators=(",", ":"), ensure_ascii=False))
            converted += 1

    if already_v2:
        return 0, converted, dropped

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines_out) + ("\n" if lines_out else ""))
    return converted, 0, dropped


def gather_inputs(paths):
    files = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            files.extend(sorted(p.rglob("mission.jsonl")))
        elif p.is_file():
            files.append(p)
        else:
            print(f"warning: no such path: {p}", file=sys.stderr)
    return files


def main(argv=None):
    ap = argparse.ArgumentParser(description="Convert v1 mission logs to schema v2.")
    ap.add_argument("paths", nargs="+", help="mission.jsonl files or directories to search")
    ap.add_argument("-o", "--output", help="output path (single input file only)")
    ap.add_argument("--in-place", action="store_true",
                    help="rewrite each file in place (original backed up to mission.v1.jsonl)")
    args = ap.parse_args(argv)

    files = gather_inputs(args.paths)
    if not files:
        print("nothing to convert", file=sys.stderr)
        return 1
    if args.output and (len(files) != 1 or args.in_place):
        ap.error("-o/--output requires exactly one input file and is incompatible with --in-place")

    total_conv = total_skip = total_drop = 0
    for in_path in files:
        if args.output:
            out_path = Path(args.output)
        elif args.in_place:
            out_path = in_path  # written after backup below
        else:
            out_path = in_path.with_name("mission.v2.jsonl")

        if args.in_place:
            backup = in_path.with_name("mission.v1.jsonl")
            if not backup.exists():
                in_path.rename(backup)
            else:
                print(f"  backup {backup} already exists; reading it", file=sys.stderr)
            conv, skip, drop = convert_file(backup, out_path)
        else:
            conv, skip, drop = convert_file(in_path, out_path)

        total_conv += conv
        total_skip += skip
        total_drop += drop
        if skip:
            print(f"{in_path}: already schema v2, skipped")
        else:
            print(f"{in_path} -> {out_path}: {conv} records"
                  f"{f', {drop} malformed dropped' if drop else ''}")

    print(f"\nDone: {total_conv} records converted, {total_skip} files already v2, "
          f"{total_drop} malformed lines dropped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
