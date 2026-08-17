"""Tests for tools/sync_rpi_logs.sh.

The script must run under macOS's system bash 3.2 (the log_server invokes it
there). Two layers:
- a static check rejecting bash-4-only constructs (mapfile bit us in the
  field; CI runs bash 5 where they silently work, so grep is the only guard)
- functional runs with stubbed ssh/rsync on PATH

Run with:  python -m pytest tests/test_sync_rpi_logs.py
"""

import os
import re
import stat
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "tools" / "sync_rpi_logs.sh"

BASH4_ONLY = [
    (r"\bmapfile\b", "mapfile (bash 4)"),
    (r"\breadarray\b", "readarray (bash 4)"),
    (r"\bdeclare\s+-[a-zA-Z]*A", "associative arrays (bash 4)"),
    (r"\$\{[A-Za-z_][A-Za-z_0-9]*(\^\^|,,)\}", "case conversion ${var^^}/${var,,} (bash 4)"),
    (r"&>>", "&>> redirect (bash 4)"),
]


def test_script_avoids_bash4_only_constructs():
    # scan code only — comments may legitimately mention the banned builtins
    code = "\n".join(line.split("#", 1)[0] for line in SCRIPT.read_text().splitlines()
                     if not line.lstrip().startswith("#"))
    hits = [name for pattern, name in BASH4_ONLY if re.search(pattern, code)]
    assert not hits, (
        f"{SCRIPT.name} uses bash-4-only constructs {hits}; "
        "macOS system bash is 3.2 — keep the script 3.2-portable")


def _stub_bin(tmp_path: Path, mission_ids):
    """Fake ssh (lists mission ids) and rsync (records calls) on PATH."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "rsync_calls.txt"
    ssh = bin_dir / "ssh"
    ssh.write_text("#!/bin/sh\n" + "".join(f"echo {m}\n" for m in mission_ids))
    rsync = bin_dir / "rsync"
    rsync.write_text(f'#!/bin/sh\necho "$@" >> "{calls}"\n')
    for f in (ssh, rsync):
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
    return bin_dir, calls


def _run(tmp_path: Path, mission_ids, args=()):
    bin_dir, calls = _stub_bin(tmp_path, mission_ids)
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["SKYDOCK_RPI_MISSIONS_DIR"] = str(tmp_path / "out")
    bash = "/bin/bash" if sys.platform == "darwin" else "bash"  # macOS: real 3.2
    r = subprocess.run([bash, str(SCRIPT), *args], env=env,
                       capture_output=True, text=True, timeout=30)
    return r, calls


def test_syncs_each_mission_listed_by_the_pi(tmp_path):
    r, calls = _run(tmp_path, ["0001", "0002"])
    assert r.returncode == 0, r.stdout + r.stderr
    logged = calls.read_text() if calls.exists() else ""
    # two rsync invocations per mission (files + frames)
    for mid in ("0001", "0002"):
        assert f"missions/{mid}/" in logged, (logged, r.stdout, r.stderr)


def test_no_missions_on_pi_exits_cleanly(tmp_path):
    # bash 3.2 + set -u dies expanding an empty array; must exit 0 instead.
    r, calls = _run(tmp_path, [])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "no missions" in r.stdout


def test_explicit_mission_ids_skip_the_listing(tmp_path):
    r, calls = _run(tmp_path, ["9999"], args=("0042",))
    assert r.returncode == 0, r.stdout + r.stderr
    logged = calls.read_text()
    assert "missions/0042/" in logged
    assert "9999" not in logged  # ssh listing unused when ids are given
