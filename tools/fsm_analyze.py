import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


@dataclass
class Transition:
    time_ns: int
    state_from: str
    state_to: str


def iter_events(path: Path) -> Iterable[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mission_jsonl", type=Path, help="Path to missions/XXXX/mission.jsonl")
    args = ap.parse_args()

    transitions: list[Transition] = []
    ticks_by_state = defaultdict(int)

    for ev in iter_events(args.mission_jsonl):
        if ev.get("event") == "fsm_transition":
            tns = int(ev.get("time_ns") or 0)
            transitions.append(
                Transition(
                    time_ns=tns,
                    state_from=str(ev.get("state_from")),
                    state_to=str(ev.get("state_to")),
                )
            )
        elif ev.get("event") == "fsm_tick":
            ticks_by_state[str(ev.get("state"))] += 1

    transitions.sort(key=lambda t: t.time_ns)

    print(f"Transitions: {len(transitions)}")
    for t in transitions[:200]:
        print(f"{t.time_ns} {t.state_from} -> {t.state_to}")

    if ticks_by_state:
        print("\nTick counts (DEBUG fsm_tick):")
        for k, v in sorted(ticks_by_state.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"{k}: {v}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

