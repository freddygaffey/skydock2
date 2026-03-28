"""Read mission.jsonl and list missions / sim truth files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator


def iter_events(path: Path) -> Iterator[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def mission_paths(missions_root: Path) -> list[Path]:
    if not missions_root.exists():
        return []
    dirs = [p for p in missions_root.iterdir() if p.is_dir() and p.name.isdigit()]
    return sorted(dirs, key=lambda p: int(p.name))


def sim_files(sim_data_root: Path) -> list[str]:
    if not sim_data_root.exists():
        return []
    files = [p.name for p in sim_data_root.iterdir() if p.is_file() and p.suffix == ".json"]
    return sorted(files)


def resolve_mission_log(missions_root: Path, mission_id: str) -> Path | None:
    if not mission_id.isdigit():
        return None
    p = missions_root / mission_id / "mission.jsonl"
    return p if p.exists() else None
