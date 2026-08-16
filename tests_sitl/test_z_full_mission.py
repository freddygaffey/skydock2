"""Black-box full-mission test: run main.py against SITL on a fresh mission
and assert the system actually finds the weeds.

Uses sim_data/blackbox6.json — 6 weeds, scan lines at 4 m spacing so every
weed is inside the camera's ~2.8 m cross-track half-swath (unlike cmac2's
8 m rows). The mission runs end to end (scan -> cluster -> goto/homing/spray
-> RTL); main.py exits on its own when every weed is sprayed.

Pass criteria are statistical, not exact: sim imperfections + detection
latency are on, so require >= 5 of 6 weeds found within 2 m and <= 5 false
weeds (observed 1-4 across runs; some are split-cluster projection artifacts
of true weeds, tracked separately). The sim RNG is seeded, so runs are
near-reproducible.

Named test_z_* so it collects AFTER the smoke tests: they leave the vehicle
in a clean hover this mission can start from, whereas running the mission
first leaves the FC in RTL/landing and breaks their arm/velocity steps.

Run with:  python3 -m pytest tests_sitl/ -q
"""

import json
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

REPO = Path(__file__).resolve().parent.parent
MISSION_JSON = REPO / "sim_data" / "blackbox6.json"
SPEEDUP = 10
TIMEOUT_S = 900


def test_full_mission_finds_the_weeds(sitl, telemetry):
    # The session Telemetry binds udp:14550; main.py needs to bind the same
    # port to talk to SITL. Close it — this test is named to run last, so no
    # later test needs the fixture.
    try:
        telemetry.connection.close()
    except Exception:
        pass
    time.sleep(2)
    # main.py starts a status server on 8080; a live dev session would collide.
    try:
        s = socket.socket()
        s.bind(("127.0.0.1", 8080))
        s.close()
    except OSError:
        import pytest
        pytest.skip("port 8080 busy — another main.py session is running")

    before = {p.name for p in (REPO / "missions").iterdir() if p.is_dir()}

    proc = subprocess.Popen(
        [sys.executable, "main.py", "-s", str(MISSION_JSON), "--speedup", str(SPEEDUP)],
        cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    # main.py's FSM loop announces completion but the process then hangs on
    # non-daemon threads (telemetry passer / status server), so wait for the
    # RTL marker in its output rather than for process exit.
    lines: list[str] = []
    deadline = time.time() + TIMEOUT_S
    completed = False
    try:
        for line in proc.stdout:
            lines.append(line)
            if "rtl state reached" in line:
                completed = True
                break
            if time.time() > deadline:
                break
    finally:
        proc.kill()
    out = "".join(lines)
    assert completed, (
        f"mission did not reach RTL within {TIMEOUT_S}s; last output:\n{out[-3000:]}")

    new_dirs = sorted({p.name for p in (REPO / "missions").iterdir() if p.is_dir()} - before)
    assert new_dirs, f"no mission directory created; output tail:\n{out[-3000:]}"
    mission_jsonl = REPO / "missions" / new_dirs[-1] / "mission.jsonl"
    assert mission_jsonl.exists(), f"{mission_jsonl} missing; output tail:\n{out[-3000:]}"

    sys.path.insert(0, str(REPO / "tools"))
    from sim_accuracy import load_truth, load_predictions, match

    truth = load_truth(MISSION_JSON)
    preds = load_predictions(mission_jsonl)
    tp, fp, fn = match(preds, truth, thresh_m=2.0)

    detail = (f"mission {new_dirs[-1]}: TP={tp} FP={fp} FN={fn} "
              f"(truth={len(truth)}, predicted={len(preds)})")
    print(detail)
    assert tp >= 5, f"found too few weeds — {detail}\noutput tail:\n{out[-3000:]}"
    assert fp <= 5, f"too many false weeds — {detail}"
