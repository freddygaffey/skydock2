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


def iter_events_of_kind(path: Path, event: str) -> Iterator[dict[str, Any]]:
    """Yield events with ``event == event`` without JSON-decoding unrelated lines (faster for rare kinds)."""
    spaced = f'"event": "{event}"'
    compact = f'"event":"{event}"'
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if spaced not in line and compact not in line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("event") == event:
                yield obj


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


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def truth_files_for_ui(sim_data_root: Path, missions_src: str) -> list[str]:
    """Basenames for the truth-file dropdown: sim_data JSON, and for RPi also ``real_missions/*.json``."""
    names = set(sim_files(sim_data_root))
    if missions_src == "rpi":
        rm = _repo_root() / "real_missions"
        if rm.is_dir():
            names.update(p.name for p in rm.iterdir() if p.is_file() and p.suffix == ".json")
    return sorted(names)


def resolve_mission_log(missions_root: Path, mission_id: str) -> Path | None:
    if not mission_id.isdigit():
        return None
    p = missions_root / mission_id / "mission.jsonl"
    return p if p.exists() else None


def real_missions_root() -> Path:
    return _repo_root() / "real_missions"


def setup_root_for_target(target: str, sim_data_root: Path | None = None) -> Path:
    t = (target or "real").strip().lower()
    if t == "sim":
        if sim_data_root is None:
            raise ValueError("sim_data_root is required for target=sim")
        return Path(sim_data_root)
    return real_missions_root()


def list_setups(target: str, sim_data_root: Path | None = None) -> list[str]:
    root = setup_root_for_target(target, sim_data_root)
    if not root.exists():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_file() and p.suffix == ".json")


def list_real_mission_setups() -> list[str]:
    return list_setups("real")


def _safe_setup_name(name: str) -> str:
    safe = Path(name or "").name
    if not safe or safe != name or not safe.endswith(".json"):
        raise ValueError("Invalid setup filename")
    return safe


def load_real_mission_setup(name: str) -> dict[str, Any]:
    safe = _safe_setup_name(name)
    p = real_missions_root() / safe
    if not p.is_file():
        raise FileNotFoundError(safe)
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("Setup must be a JSON object")
    return data


def save_real_mission_setup(name: str, payload: dict[str, Any]) -> Path:
    safe = _safe_setup_name(name)
    rm = real_missions_root()
    rm.mkdir(parents=True, exist_ok=True)
    p = rm / safe
    with open(p, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    return p


def load_setup(name: str, target: str, sim_data_root: Path | None = None) -> dict[str, Any]:
    safe = _safe_setup_name(name)
    p = setup_root_for_target(target, sim_data_root) / safe
    if not p.is_file():
        raise FileNotFoundError(safe)
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("Setup must be a JSON object")
    return data


def save_setup(name: str, payload: dict[str, Any], target: str, sim_data_root: Path | None = None) -> Path:
    safe = _safe_setup_name(name)
    root = setup_root_for_target(target, sim_data_root)
    root.mkdir(parents=True, exist_ok=True)
    p = root / safe
    with open(p, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    return p
